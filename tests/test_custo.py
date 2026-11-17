"""Fontes falsas e integração da CLI: não consulta contas nem chama modelos."""
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import custo
import kit


class MedicaoTest(unittest.TestCase):
    def setUp(self):
        self.temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporaria.cleanup)
        self.raiz = Path(self.temporaria.name)
        self.ambiente = patch.dict(os.environ, {
            "KIT_IA_HOME": str(self.raiz / "kit"),
            "KIT_IA_CLAUDE_DIR": str(self.raiz / "claude"),
            "KIT_IA_CODEX_DIR": str(self.raiz / "codex"),
            "KIT_IA_ANTIGRAVITY_DIR": str(self.raiz / "antigravity"),
        })
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)

    def gravar(self, caminho, linhas):
        arquivo = self.raiz / caminho
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text("\n".join(json.dumps(linha) for linha in linhas) + "\n", encoding="utf-8")
        return arquivo

    def rodar(self, *argumentos):
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = kit.main(["custo", *argumentos])
        return codigo, saida.getvalue(), erro.getvalue()

    def test_claude_deduplica_request_e_message_id_inclusive_subagente(self):
        linha = {"timestamp": "2026-11-16T10:00:00Z", "requestId": "r1", "cwd": str(self.raiz),
                 "gitBranch": "task/BL-LU-3", "message": {"id": "m1", "model": "modelo",
                 "usage": {"input_tokens": 10, "output_tokens": 4,
                           "cache_read_input_tokens": 20, "cache_creation_input_tokens": 6}}}
        segunda = {**linha, "timestamp": "2026-11-16T10:02:00Z"}
        self.gravar("claude/projeto/a.jsonl", [linha, segunda])
        sem_request = {**linha, "isSidechain": True, "message": {**linha["message"], "id": "m2"}}
        sem_request.pop("requestId")
        self.gravar("claude/projeto/subagents/b.jsonl", [sem_request, sem_request])
        registros, avisos = custo.coletar()
        self.assertFalse(avisos)
        self.assertEqual(len(registros), 2)
        self.assertEqual({item["papel"] for item in registros}, {"principal", "subagente"})
        grupos = custo.agrupar(registros, "task", {})
        self.assertEqual(grupos[0]["tokens"], 80)
        self.assertEqual(grupos[0]["minutos"], 2)
        self.assertIsNone(grupos[0]["custo_usd"])

    def codex(self):
        return self.gravar("codex/2026/a.jsonl", [
            {"type": "session_meta", "timestamp": "2026-11-16T10:00:00Z", "payload": {
                "cwd": str(self.raiz), "git": {"branch": "task/BL-LU-3"}}},
            {"type": "turn_context", "payload": {"model": "modelo", "cwd": str(self.raiz)}},
            {"type": "event_msg", "timestamp": "2026-11-16T10:01:00Z", "payload": {
                "type": "token_count", "info": {"total_token_usage": {"input_tokens": 30, "output_tokens": 2}}}},
            {"type": "event_msg", "timestamp": "2026-11-16T10:03:00Z", "payload": {
                "type": "token_count", "info": {"total_token_usage": {"input_tokens": 100,
                    "cached_input_tokens": 40, "output_tokens": 10, "reasoning_output_tokens": 3}}}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
        ])

    def test_codex_ultimo_acumulado_cache_e_raciocinio_nao_sao_somados(self):
        self.codex()
        registros, _ = custo.coletar()
        grupo = custo.agrupar(registros, "task", {})[0]
        self.assertEqual((grupo["tokens"], grupo["cache_leitura"], grupo["minutos"]), (110, 40, 3))

    def test_claude_distribui_tempo_entre_modelos_sem_duplicar_sessao(self):
        self.gravar("claude/a.jsonl", [
            {"timestamp": "2026-11-16T10:00:00Z"},
            {"timestamp": "2026-11-16T10:01:00Z", "requestId": "um", "message": {
                "model": "primeiro", "usage": {"input_tokens": 10, "output_tokens": 1}}},
            {"timestamp": "2026-11-16T10:02:00Z", "requestId": "dois", "message": {
                "model": "segundo", "usage": {"input_tokens": 20, "output_tokens": 2}}},
            {"timestamp": "2026-11-16T10:04:00Z"},
        ])
        grupos = custo.agrupar(custo.coletar()[0], "modelo", {})
        self.assertEqual(sum(item["minutos"] for item in grupos), 4)
        self.assertEqual({item["modelo"]: item["minutos"] for item in grupos}, {"primeiro": 2, "segundo": 2})

    def test_codex_modelo_muda_avisa_e_atribui_ultimo(self):
        arquivo = self.codex()
        with arquivo.open("a", encoding="utf-8") as fluxo:
            fluxo.write(json.dumps({"type": "turn_context", "payload": {"model": "outro"}}) + "\n")
        registros, avisos = custo.coletar()
        self.assertEqual(registros[0]["modelo"], "outro")
        self.assertIn("último modelo", avisos[0])

    def test_claude_tempo_usa_extremos_mesmo_com_eventos_fora_de_ordem(self):
        self.gravar("claude/a.jsonl", [
            {"timestamp": "2026-11-16T10:02:00Z", "requestId": "um", "message": {
                "model": "modelo", "usage": {"input_tokens": 1, "output_tokens": 1}}},
            {"timestamp": "2026-11-16T10:00:00Z"},
            {"timestamp": "2026-11-16T10:04:00Z"},
            {"timestamp": "2026-11-16T10:03:00Z"},
        ])
        self.assertEqual(custo.agrupar(custo.coletar()[0], "modelo", {})[0]["minutos"], 4)

    def test_antigravity_tokens_nulos_e_tempo_parcial(self):
        pasta = self.raiz / "antigravity"
        pasta.mkdir()
        with contextlib.closing(sqlite3.connect(pasta / "conversation_summaries.db")) as banco:
            with banco:
                banco.execute("CREATE TABLE conversation_summaries (conversation_id, workspace_uris, last_user_input_time, last_modified_time)")
                banco.execute("INSERT INTO conversation_summaries VALUES (?, ?, ?, ?)",
                              ("a", json.dumps([(self.raiz / "BL-LU-3").as_uri()]),
                               "2026-11-16T10:00:00Z", "2026-11-16T10:04:00Z"))
        codigo, saida, _ = self.rodar("--json")
        grupo = json.loads(saida)["grupos"][0]
        self.assertEqual(codigo, 0)
        self.assertEqual(grupo["task"], "BL-LU-3")
        self.assertIsNone(grupo["tokens"])
        self.assertEqual(grupo["minutos"], 4)
        self.assertTrue(grupo["parcial"])
        self.assertIn("tokens desconhecidos", json.loads(saida)["avisos"][0])

    def test_kit_usa_custo_real_e_duracao(self):
        self.gravar("kit/uso.jsonl", [{"data": "2026-11-16T10:00:00Z", "modelo": "m",
                    "entrada": 20, "saida": 5, "custo_usd": .02, "duracao_segundos": 90,
                    "task": "BL-LU-3", "pasta": str(self.raiz)}])
        registros, _ = custo.coletar()
        grupo = custo.agrupar(registros, "agente", {})[0]
        self.assertEqual((grupo["tokens"], grupo["minutos"], grupo["custo_usd"]), (25, 1.5, .02))

    def test_precos_diferenciam_cache_e_custo_do_provedor_tem_prioridade(self):
        item = {"modelo": "m", "entrada": 100, "saida": 10, "cache_leitura": 40, "cache_escrita": 20}
        tarifas = {"m": {"entrada": 2, "saida": 10, "cache_leitura": 1, "cache_escrita": 3}}
        self.assertAlmostEqual(custo.calcular_custo(item, tarifas), .00028)
        self.assertEqual(custo.calcular_custo({**item, "custo_usd": 0}, tarifas), 0)
        self.assertIsNone(custo.calcular_custo(item, {"m": {"entrada": 2}}))

    def test_orcamento_excede_ou_respeita_e_ignora_outro_projeto(self):
        self.codex()
        projeto = self.raiz / ".kit-ia/projeto.yaml"
        projeto.parent.mkdir()
        for tokens, minutos, esperado in ((109, 3, 1), (110, 2, 1), (110, 3, 0)):
            with self.subTest(tokens=tokens, minutos=minutos):
                projeto.write_text(f"orcamento:\n  por_task: {{ tokens: {tokens}, minutos: {minutos} }}", encoding="utf-8")
                codigo, saida, _ = self.rodar("--verificar-orcamento", str(self.raiz), "--json")
                self.assertEqual(codigo, esperado)
                self.assertEqual(bool(json.loads(saida)["estouros"]), bool(esperado))
        outro = self.raiz / "outro/.kit-ia/projeto.yaml"
        outro.parent.mkdir(parents=True)
        outro.write_text("orcamento:\n  por_task: {tokens: 0, minutos: 0}", encoding="utf-8")
        self.assertEqual(self.rodar("--verificar-orcamento", str(outro.parent.parent))[0], 0)

    def test_filtros_agrupamentos_e_lote_markdown(self):
        self.codex()
        for por, esperado in (("task", "BL-LU-3"), ("agente", "codex"), ("modelo", "modelo"), ("papel", "principal")):
            codigo, saida, _ = self.rodar("--desde", "2026-11-16", "--por", por, "--json")
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(saida)["grupos"][0][por], esperado)
        self.assertEqual(json.loads(self.rodar("--desde", "2026-11-17", "--json")[1])["grupos"], [])
        saida = self.rodar("--lote", "BL-LU-3,BL-LU-4")[1]
        self.assertIn("| BL-LU-3 | 110 | 3.00 | — |", saida)
        self.assertIn("Maior fonte de gasto: codex", saida)
        self.assertNotIn("BL-LU-3 |", self.rodar("--lote", "BL-LU-4")[1])

    def test_erros_esperados_sem_stack_trace(self):
        self.assertEqual(self.rodar("--desde", "ontem")[0], 1)
        projeto = self.raiz / "projeto.yaml"
        projeto.write_text("orcamento: |\n  errado", encoding="utf-8")
        codigo, _, erro = self.rodar("--verificar-orcamento", str(projeto))
        self.assertEqual(codigo, 1)
        self.assertIn("linha 1", erro)
        for conteudo in ("orcamento: {}", "orcamento: 1", "orcamento: {por_task: []}"):
            projeto.write_text(conteudo, encoding="utf-8")
            self.assertEqual(self.rodar("--verificar-orcamento", str(projeto))[0], 1)

    def test_json_truncado_avisa_e_preserva_o_restante(self):
        arquivo = self.codex()
        with arquivo.open("a", encoding="utf-8") as fluxo:
            fluxo.write('{"incompleto":')
        registros, avisos = custo.coletar()
        self.assertEqual(len(registros), 1)
        self.assertIn("inválida", avisos[0])

    def test_task_branch_tem_prioridade_e_ausencia_explicita(self):
        self.assertEqual(custo.detectar_task("task/BL-LU-3", "BL-AA-1"), "BL-LU-3")
        self.assertEqual(custo.detectar_task("", "/projeto/BL-A1-25"), "BL-A1-25")
        self.assertEqual(custo.detectar_task(), "(sem task)")

    def test_ollama_e_uso_ausente(self):
        uso = custo.uso_resposta({"prompt_eval_count": 12, "eval_count": 3}, "openai")
        self.assertEqual((uso["entrada"], uso["saida"]), (12, 3))
        self.assertIsNone(custo.uso_resposta({}, "openai")["entrada"])

    def test_url_sem_credenciais_e_task_automatica_no_registro(self):
        with patch("custo.branch_atual", return_value="task/BL-LU-3"):
            custo.registrar_uso({"protocolo": "openai", "url": "https://usuario:senha@local/v1?key=segredo#chave",
                                "modelo": "m"}, {}, custo.data("2026-11-16"), 2)
        texto = (self.raiz / "kit/uso.jsonl").read_text(encoding="utf-8")
        item = json.loads(texto)
        self.assertEqual(item["task"], "BL-LU-3")
        self.assertEqual(item["url"], "https://local/v1")
        self.assertNotIn("segredo", texto)
        self.assertNotIn("senha", texto)

    def test_cache_anthropic_e_openai_normalizam_entrada(self):
        anthropic = custo.uso_resposta({"usage": {"input_tokens": 10, "output_tokens": 5,
            "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30}}, "anthropic")
        openai = custo.uso_resposta({"usage": {"prompt_tokens": 60, "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 20}}}, "openai")
        self.assertEqual(anthropic["entrada"], openai["entrada"])
        self.assertEqual(anthropic["cache_escrita"], 30)


class YamlTest(unittest.TestCase):
    def test_template_real(self):
        projeto = kit.ler_projeto(kit.RAIZ / "templates/projeto.yaml")
        self.assertEqual(projeto["orcamento"]["por_task"], {"tokens": 400000, "minutos": 30})
        self.assertEqual(projeto["branches"]["destinos"], ["main"])
        self.assertEqual(projeto["projeto"]["nome"], "{{nome}}")

    def test_subconjunto_listas_mapas_aspas_numeros_comentarios(self):
        texto = '''nome: "um # nome" # comentário
lista:
  - um
  - 'dois: três'
mapa: { a: 1, b: [x, "y,z"], c: { outro: 2.5 } }
url: https://local:8080/v1
'''
        dados = custo.ler_yaml(texto)
        self.assertEqual(dados["lista"], ["um", "dois: três"])
        self.assertEqual(dados["mapa"], {"a": 1, "b": ["x", "y,z"], "c": {"outro": 2.5}})
        self.assertEqual(dados["nome"], "um # nome")
        self.assertEqual(dados["url"], "https://local:8080/v1")

    def test_sintaxe_nao_suportada_tem_linha(self):
        for texto in ("a: |", "a: &ancora x", "a: *ancora", "a: !tag x", "a: [x", "a: x\n  b: y", "a: 1\na: 2", "\ta: 1", "---"):
            with self.subTest(texto=texto), self.assertRaisesRegex(ValueError, "linha [12]:"):
                custo.ler_yaml(texto)


if __name__ == "__main__":
    unittest.main()
