"""Fontes falsas e integração da CLI: não consulta contas nem chama modelos."""
import contextlib
import io
import json
import os
import random
import sqlite3
import subprocess
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
            codigo = kit.main(["cost", *argumentos])
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

    def test_claude_consolida_uso_atualizado_sem_duplicar_resposta(self):
        for identificador in ("requestId", "message.id"):
            for outro_arquivo in (False, True):
                with self.subTest(identificador=identificador, outro_arquivo=outro_arquivo):
                    linha = {"timestamp": "2026-11-16T10:00:00Z", "cwd": str(self.raiz),
                             "gitBranch": "task/BL-LU-3", "message": {"id": "m1", "model": "modelo",
                             "usage": {"input_tokens": 399000, "output_tokens": 35}}}
                    if identificador == "requestId":
                        linha["requestId"] = "r1"
                    atualizada = {**linha, "timestamp": "2026-11-16T10:02:00Z", "message": {
                        **linha["message"], "usage": {"input_tokens": 399000, "output_tokens": 4359}}}
                    # A cópia antiga no arquivo seguinte não pode apagar a atualização mais recente.
                    self.gravar("claude/a.jsonl", [linha, atualizada, atualizada])
                    if outro_arquivo:
                        self.gravar("claude/b.jsonl", [linha])
                    else:
                        (self.raiz / "claude/b.jsonl").unlink(missing_ok=True)
                    registros, avisos = custo.coletar()
                    self.assertFalse(avisos)
                    self.assertEqual(len(registros), 1)
                    grupo = custo.agrupar(registros, "task", {})[0]
                    self.assertEqual((grupo["entrada"], grupo["saida"], grupo["tokens"]),
                                     (399000, 4359, 403359))
                    self.assertEqual(grupo["minutos"], 2)

    def test_claude_atualiza_cache_sem_somar_snapshots(self):
        linha = {"requestId": "r1", "message": {"id": "m1", "model": "modelo", "usage": {
            "input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 30}}}
        atualizada = {**linha, "message": {**linha["message"], "usage": {
            "input_tokens": 15, "output_tokens": 5, "cache_read_input_tokens": 25,
            "cache_creation_input_tokens": 35}}}
        self.gravar("claude/a.jsonl", [linha, atualizada, atualizada])
        grupo = custo.agrupar(custo.coletar()[0], "task", {})[0]
        self.assertEqual((grupo["entrada"], grupo["saida"], grupo["cache_leitura"],
                          grupo["cache_escrita"], grupo["tokens"]), (75, 5, 25, 35, 80))

    def test_claude_uso_parcial_preserva_subtotais_conhecidos(self):
        completo = {"input_tokens": 500000, "output_tokens": 10,
                    "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30}
        tarifas = {"modelo": {"entrada": 1, "saida": 1, "cache_leitura": 1, "cache_escrita": 1}}
        for campo in completo:
            for parcial_primeiro in (False, True):
                with self.subTest(campo=campo, parcial_primeiro=parcial_primeiro):
                    parcial = {**dict.fromkeys(completo, 1), campo: None}
                    usos = [completo, parcial]
                    if parcial_primeiro:
                        usos.reverse()
                    self.gravar("claude/a.jsonl", [
                        {"requestId": f"r{indice}", "message": {"model": "modelo", "usage": uso}}
                        for indice, uso in enumerate(usos)])
                    registros, avisos = custo.coletar()
                    self.assertFalse(avisos)
                    self.assertEqual(len(registros), 1)
                    grupo = custo.agrupar(registros, "task", tarifas)[0]
                    entrada = sum(completo[chave] + (parcial[chave] or 0) for chave in
                                  ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                    saida = completo["output_tokens"] + (parcial["output_tokens"] or 0)
                    self.assertEqual(grupo["entrada"], entrada)
                    self.assertEqual(grupo["saida"], saida)
                    self.assertEqual(grupo["tokens"], entrada + saida)
                    self.assertEqual(grupo["cache_leitura"], 20 + (parcial["cache_read_input_tokens"] or 0))
                    self.assertEqual(grupo["cache_escrita"], 30 + (parcial["cache_creation_input_tokens"] or 0))
                    self.assertTrue(grupo["parcial"])
                    self.assertIsNone(grupo["custo_usd"])

    def test_claude_atualizacao_desconhecida_preserva_cada_contador_da_resposta(self):
        completo = {"input_tokens": 500000, "output_tokens": 10,
                    "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30}
        tarifas = {"modelo": dict.fromkeys(("entrada", "saida", "cache_leitura", "cache_escrita"), 1)}
        for identificador in ("requestId", "message.id"):
            for campo in completo:
                for ordem in ((0, 1, 2), (2, 0, 1), (0, 2, 1)):
                    with self.subTest(identificador=identificador, campo=campo, ordem=ordem):
                        usos = [completo, {**completo, "output_tokens": 11},
                                {**completo, "output_tokens": 12, campo: None}]
                        linhas = [{"timestamp": f"2026-11-16T10:0{indice}:00Z", "message": {
                            "id": "m1", "model": "modelo", "usage": usos[indice]}} for indice in ordem]
                        if identificador == "requestId":
                            for linha in linhas:
                                linha["requestId"] = "r1"
                        self.gravar("claude/a.jsonl", linhas)
                        registros, avisos = custo.coletar()
                        self.assertFalse(avisos)
                        self.assertEqual(len(registros), 1)
                        grupo = custo.agrupar(registros, "task", tarifas)[0]
                        saida = 11 if campo == "output_tokens" else 12
                        self.assertEqual((grupo["entrada"], grupo["saida"], grupo["cache_leitura"],
                                          grupo["cache_escrita"], grupo["tokens"]),
                                         (500050, saida, 20, 30, 500050 + saida))
                        self.assertEqual(grupo["minutos"], 2)
                        self.assertTrue(grupo["parcial"])
                        self.assertIsNone(grupo["custo_usd"])

    def test_anthropic_entrada_desconhecida_preserva_cache_como_limite_inferior(self):
        for leitura, escrita in ((500000, 0), (0, 500000), (300000, 200000)):
            with self.subTest(leitura=leitura, escrita=escrita):
                uso = custo.uso_resposta({"usage": {"input_tokens": None, "output_tokens": 1,
                    "cache_read_input_tokens": leitura, "cache_creation_input_tokens": escrita}}, "anthropic")
                self.assertEqual(uso["entrada"], 500000)
                item = custo.registro("kit", "modelo", "executar", str(self.raiz), "task/BL-LU-3",
                                      None, None, uso)
                grupo = custo.agrupar([item], "task", {"modelo": {
                    "entrada": 1, "saida": 1, "cache_leitura": 1, "cache_escrita": 1}})[0]
                self.assertEqual((grupo["tokens"], grupo["cache_leitura"], grupo["cache_escrita"]),
                                 (500001, leitura, escrita))
                self.assertTrue(grupo["parcial"])
                self.assertIsNone(grupo["custo_usd"])

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

    def test_codex_troca_sem_novo_uso_preserva_modelo_que_consumiu(self):
        arquivo = self.codex()
        with arquivo.open("a", encoding="utf-8") as fluxo:
            fluxo.write(json.dumps({"type": "turn_context", "payload": {"model": "outro"}}) + "\n")
        registros, avisos = custo.coletar()
        self.assertEqual(registros[0]["modelo"], "modelo")
        self.assertEqual(registros[0]["entrada"], 100)
        self.assertFalse(avisos)

    def test_codex_distribui_deltas_por_modelo_e_calcula_custo_correto(self):
        linhas = [{"type": "session_meta", "timestamp": "2026-11-16T10:00:00Z",
                   "payload": {"cwd": str(self.raiz), "git": {"branch": "task/BL-LU-3"}}}]
        for minuto, modelo, entrada in ((1, "primeiro", 100), (2, "segundo", 120),
                                       (3, "segundo", 120), (4, "primeiro", 150)):
            linhas.extend([
                {"type": "turn_context", "payload": {"model": modelo}},
                {"type": "event_msg", "timestamp": f"2026-11-16T10:0{minuto}:00Z", "payload": {
                    "type": "token_count", "info": {"total_token_usage": {
                        "input_tokens": entrada, "output_tokens": 0, "cached_input_tokens": 0}}}},
            ])
        arquivo = self.gravar("codex/a.jsonl", linhas[:5])
        precos = {"primeiro": {"entrada": 1}, "segundo": {"entrada": 10}}
        registros, avisos = custo.coletar()
        grupos = custo.agrupar(registros, "modelo", precos)
        self.assertEqual({item["modelo"]: item["tokens"] for item in grupos}, {"primeiro": 100, "segundo": 20})
        self.assertAlmostEqual(sum(item["custo_usd"] for item in grupos), .0003)
        self.assertEqual(sum(item["minutos"] for item in grupos), 2)
        self.assertEqual(custo.agrupar(registros, "task", precos)[0]["tokens"], 120)
        self.assertFalse(avisos)
        # Repetição do mesmo acumulado e retorno ao primeiro modelo não duplicam uso.
        arquivo.write_text("\n".join(json.dumps(linha) for linha in linhas), encoding="utf-8")
        grupos = custo.agrupar(custo.coletar()[0], "modelo", precos)
        self.assertEqual({item["modelo"]: item["tokens"] for item in grupos}, {"primeiro": 130, "segundo": 20})
        self.assertEqual(sum(item["minutos"] for item in grupos), 4)

    def test_codex_acumulado_regredido_tem_uso_e_custo_desconhecidos(self):
        for total in ({"input_tokens": 2, "output_tokens": 1, "cached_input_tokens": 40},
                      {"input_tokens": 110, "output_tokens": 10, "cached_input_tokens": 30}):
            with self.subTest(total=total):
                arquivo = self.codex()
                with arquivo.open("a", encoding="utf-8") as fluxo:
                    fluxo.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count",
                        "info": {"total_token_usage": total}}}) + "\n")
                registros, avisos = custo.coletar()
                grupo = custo.agrupar(registros, "task", {"modelo": {
                    "entrada": 1, "saida": 1, "cache_leitura": 1}})[0]
                self.assertTrue(grupo["parcial"])
                self.assertIsNone(grupo["custo_usd"])
                self.assertTrue(any("regrediu" in aviso for aviso in avisos))

    def test_codex_regressao_preserva_limite_inferior_e_estouro_do_orcamento(self):
        projeto = self.raiz / ".kit-ia/projeto.yaml"
        projeto.parent.mkdir()
        projeto.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
        linhas = [{"type": "session_meta", "timestamp": "2026-11-16T10:00:00Z", "payload": {
            "cwd": str(self.raiz), "model": "modelo", "git": {"branch": "task/BL-LU-3"}}}]
        for total, esperado in ((500000, 500000), (10, 500000), (20, 500000), (500010, 500010)):
            linhas.append({"type": "event_msg", "timestamp": "2026-11-16T10:01:00Z", "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": total, "output_tokens": 0, "cached_input_tokens": 0}}}})
            self.gravar("codex/a.jsonl", linhas)
            with self.subTest(total=total):
                codigo, saida, _ = self.rodar("--check-budget", str(self.raiz), "--json")
                dados = json.loads(saida)
                self.assertEqual(codigo, 1)
                self.assertEqual(dados["grupos"][0]["tokens"], esperado)
                self.assertEqual(len(dados["estouros"]), 1)
                if total != 500000:
                    grupo = custo.agrupar(custo.coletar()[0], "task", {"modelo": {"entrada": 1}})[0]
                    self.assertTrue(grupo["parcial"])
                    self.assertIsNone(grupo["custo_usd"])
                    self.assertTrue(any("regrediu" in aviso for aviso in dados["avisos"]))

    def test_codex_sessao_retomada_separa_tasks_e_intervalos(self):
        projeto = self.raiz / ".kit-ia/projeto.yaml"
        projeto.parent.mkdir()
        projeto.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
        # Isola cada dimensão da chave: a branch pode mudar na mesma pasta, e vice-versa.
        for dimensao in ("branch", "pasta", "papel"):
            with self.subTest(dimensao=dimensao):
                linhas = []
                for indice in (0, 1):
                    metadados = {"cwd": str(self.raiz), "model": "modelo"}
                    if dimensao == "pasta":
                        metadados["cwd"] = str(self.raiz / f"BL-LU-{3 + indice}")
                    else:
                        metadados["git"] = {"branch": f"task/BL-LU-{3 + indice if dimensao == 'branch' else 3}"}
                    if dimensao == "papel" and indice == 0:
                        metadados["agent_role"] = "executor"
                    linhas.extend([
                        {"type": "session_meta", "timestamp": f"2026-11-16T10:0{indice}:00Z",
                         "payload": metadados},
                        {"type": "event_msg", "timestamp": f"2026-11-16T10:0{indice + 1}:00Z", "payload": {
                            "type": "token_count", "info": {"total_token_usage": {
                                "input_tokens": 300000 * (indice + 1), "output_tokens": 0}}}},
                    ])
                self.gravar("codex/a.jsonl", linhas)
                registros, avisos = custo.coletar()
                self.assertFalse(avisos)
                self.assertEqual(len(registros), 2)
                self.assertEqual([item["entrada"] for item in registros], [300000, 300000])
                self.assertEqual([item["minutos"] for item in registros], [1, 1])
                codigo, saida, _ = self.rodar("--check-budget", str(self.raiz), "--json")
                dados = json.loads(saida)
                if dimensao == "papel":
                    self.assertEqual({item["papel"] for item in registros}, {"principal", "subagente"})
                    self.assertEqual(codigo, 1)  # Dois papéis ainda consomem o orçamento da mesma task.
                    self.assertEqual(dados["grupos"][0]["tokens"], 600000)
                else:
                    # Revisão 2: orçamento usa a sessão inteira por task, preservando a estimativa.
                    self.assertEqual(codigo, 1)
                    self.assertEqual(len(dados["estouros"]), 2)
                    self.assertEqual({item["limite_superior_tokens"] for item in dados["grupos"]}, {600000})
                    self.assertEqual({item["task"]: (item["tokens"], item["minutos"])
                                      for item in dados["grupos"]},
                                     {"BL-LU-3": (300000, 1), "BL-LU-4": (300000, 1)})

    def preparar_orcamento(self, tokens=400000, minutos=30):
        projeto = self.raiz / ".kit-ia/projeto.yaml"
        projeto.parent.mkdir(exist_ok=True)
        projeto.write_text(f"orcamento:\n  por_task: {{tokens: {tokens}, minutos: {minutos}}}", encoding="utf-8")

    def test_campo_ausente_claude_nao_apaga_500011_tokens_reportados(self):
        self.preparar_orcamento()
        self.gravar("claude/a.jsonl", [{"requestId": "r1", "cwd": str(self.raiz),
            "gitBranch": "task/BL-LU-3", "timestamp": f"2026-11-17T00:0{indice}:00Z",
            "message": {"model": "modelo", "usage": uso}} for indice, uso in enumerate([
                {"input_tokens": 500000, "output_tokens": 10}, {"output_tokens": 11}])])
        codigo, saida, _ = self.rodar("--check-budget", str(self.raiz), "--json")
        grupo = json.loads(saida)["grupos"][0]
        self.assertEqual(codigo, 1)
        self.assertEqual(grupo["tokens"], 500011)
        self.assertEqual(grupo["limite_superior_tokens"], 500011)
        self.assertTrue(grupo["medicao_incompleta"])

    def test_codex_cache_com_entrada_nula_preserva_500001_tokens_reportados(self):
        self.preparar_orcamento()
        self.gravar("codex/a.jsonl", [
            {"type": "session_meta", "timestamp": "2026-11-17T00:00:00Z", "payload": {
                "cwd": str(self.raiz), "model": "modelo", "git": {"branch": "task/BL-LU-3"}}},
            {"type": "event_msg", "timestamp": "2026-11-17T00:01:00Z", "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": None, "cached_input_tokens": 500000, "output_tokens": 1}}}}])
        codigo, saida, _ = self.rodar("--check-budget", str(self.raiz), "--json")
        grupo = json.loads(saida)["grupos"][0]
        self.assertEqual(codigo, 1)
        self.assertEqual(grupo["tokens"], 500001)
        self.assertEqual(grupo["limite_superior_tokens"], 500001)
        self.assertTrue(grupo["medicao_incompleta"])

    def test_limite_claude_usa_maximos_por_campo_sem_somar_snapshots(self):
        self.preparar_orcamento()
        self.gravar("claude/a.jsonl", [{"requestId": "r1", "cwd": str(self.raiz),
            "gitBranch": "task/BL-LU-3", "timestamp": f"2026-11-17T00:0{indice}:00Z",
            "message": {"model": "modelo", "usage": uso}} for indice, uso in enumerate([
                {"input_tokens": 500000, "output_tokens": 10},
                {"input_tokens": 1, "output_tokens": 11}])])
        codigo, saida, _ = self.rodar("--check-budget", str(self.raiz), "--json")
        grupo = json.loads(saida)["grupos"][0]
        self.assertEqual(grupo["tokens"], 12)
        self.assertEqual(grupo["limite_superior_tokens"], 500011)
        self.assertEqual(codigo, 1)

    def test_orcamento_recusa_registros_ilegíveis_inclusive_sem_contexto(self):
        self.preparar_orcamento(tokens=999999999)
        for fonte in ("claude/a.jsonl", "codex/a.jsonl", "kit/uso.jsonl"):
            for linha in ('{"truncado":', '[]', '{"payload": []}'):
                with self.subTest(fonte=fonte, linha=linha):
                    arquivo = self.gravar(fonte, [])
                    arquivo.write_text(linha, encoding="utf-8")
                    codigo, saida, erro = self.rodar("--check-budget", str(self.raiz),
                                                   "--since", "2026-11-17", "--json")
                    self.assertEqual(codigo, 1, erro)
                    self.assertTrue(json.loads(saida)["incompletas"])
                    arquivo.unlink()

    def test_codex_payload_invalido_apos_uso_valido_impede_aprovar_orcamento(self):
        self.preparar_orcamento()
        validas = [
            {"type": "session_meta", "timestamp": "2026-11-16T10:00:00Z", "payload": {
                "cwd": str(self.raiz), "model": "modelo", "git": {"branch": "task/BL-LU-3"}}},
            {"type": "event_msg", "timestamp": "2026-11-16T10:01:00Z", "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": 100, "output_tokens": 1}}}}]
        self.gravar("codex/a.jsonl", validas)
        self.assertEqual(self.rodar("--check-budget", str(self.raiz), "--json")[0], 0)
        for tipo in ("event_msg", "session_meta", "turn_context"):
            for carga in ([], "", 0, False, None, [1], "inválido"):
                for filtro in ((), ("--since", "2026-11-17")):
                    with self.subTest(tipo=tipo, payload=carga, filtro=filtro):
                        self.gravar("codex/a.jsonl", validas + [{"type": tipo, "payload": carga}])
                        codigo, saida, erro = self.rodar("--check-budget", str(self.raiz),
                                                       "--json", *filtro)
                        dados = json.loads(saida)
                        self.assertEqual(codigo, 1, erro)
                        self.assertEqual(dados["incompletas"], ["BL-LU-3: medição incompleta"])
                        self.assertTrue(any("payload inválido" in aviso for aviso in dados["avisos"]))
                        grupo = dados["grupos"][0]
                        self.assertEqual(grupo["tokens"], 101)
                        self.assertEqual(grupo["limite_superior_tokens"], 101)
                        self.assertTrue(grupo["medicao_incompleta"])

    def test_orcamento_recusa_corrupcao_com_contexto_antigo_e_data_filtrada(self):
        self.preparar_orcamento(tokens=999999999)
        arquivo = self.codex()
        for linha in ('{"truncado":', '{"type":"session_meta","payload":{"git":[1]}}',
                      '{"type":"turn_context","payload":{"cwd":[]}}',
                      '{"type":"event_msg","payload":{"type":"token_count","info":[]}}'):
            with self.subTest(linha=linha):
                self.codex()
                with arquivo.open("a", encoding="utf-8") as fluxo:
                    fluxo.write(linha + "\n")
                codigo, saida, erro = self.rodar("--check-budget", str(self.raiz),
                                               "--since", "2026-11-17", "--json")
                self.assertEqual(codigo, 1, erro)
                self.assertEqual(json.loads(saida)["incompletas"], ["BL-LU-3: medição incompleta"])

    def test_orcamento_recusa_falha_de_leitura_e_banco_antigravity_corrompido(self):
        self.preparar_orcamento()
        arquivo = self.codex()
        abrir = Path.open
        def abrir_falso(caminho, *argumentos, **opcoes):
            if caminho == arquivo:
                raise PermissionError("sem acesso")
            return abrir(caminho, *argumentos, **opcoes)
        with patch("custo.Path.open", new=abrir_falso):
            codigo, saida, erro = self.rodar("--check-budget", str(self.raiz), "--json")
        self.assertEqual(codigo, 1, erro)
        self.assertTrue(json.loads(saida)["incompletas"])
        arquivo.unlink()
        banco = self.raiz / "antigravity/conversation_summaries.db"
        banco.parent.mkdir()
        banco.write_bytes(b"banco corrompido")
        codigo, saida, erro = self.rodar("--check-budget", str(self.raiz), "--json")
        self.assertEqual(codigo, 1, erro)
        self.assertTrue(json.loads(saida)["incompletas"])

    def test_propriedade_limite_nunca_oculta_consumo_em_500_casos(self):
        gerador = random.Random(173)
        principal = self.raiz / "repositorio"
        configuracao = principal / ".kit-ia/projeto.yaml"
        configuracao.parent.mkdir(parents=True)
        configuracao.write_text("orcamento: {por_task: {tokens: 400000, minutos: 30}}", encoding="utf-8")
        worktree = self.raiz / "worktrees/BL-LU-3"
        worktree.mkdir(parents=True)
        saida_git = f"worktree {principal}\0\0worktree {worktree}\0\0"
        resultado_git = subprocess.CompletedProcess([], 0, stdout=saida_git, stderr="")
        excedidos = 0
        for caso in range(500):
            with self.subTest(caso=caso):
                agente = "claude" if caso % 2 else "codex"
                local = principal if gerador.randrange(2) else worktree
                task = f"BL-LU-{3 + caso % 7}"
                # O oráculo é o consumo conhecido antes de gerar logs, independente do leitor.
                entrada, saida = gerador.randint(100000, 600000), gerador.randint(1, 10000)
                cache = gerador.randint(0, entrada)
                real = entrada + saida
                excedidos += real > 400000
                totais = {"input_tokens": entrada, "output_tokens": saida,
                          "cached_input_tokens": cache}
                parciais = []
                for _ in range(gerador.randint(2, 6)):
                    parcial = {campo: gerador.randint(0, valor) for campo, valor in totais.items()}
                    campo = gerador.choice(list(parcial))
                    if gerador.randrange(2):
                        parcial.pop(campo)
                    else:
                        parcial[campo] = None
                    parciais.append(parcial)
                usos = [totais, totais.copy(), *parciais]
                gerador.shuffle(usos)
                linhas = []
                for indice, uso in enumerate(usos):
                    horario = f"2026-11-{16 if indice == 0 else 17}T{'23:59' if indice == 0 else '00:01'}:00Z"
                    modelo = f"modelo-{indice % 2}"
                    if agente == "claude":
                        convertido = {("cache_read_input_tokens" if campo == "cached_input_tokens" else campo): valor
                                      for campo, valor in uso.items()}
                        # Claude informa entrada sem cache, diferentemente do acumulado Codex.
                        if numero_entrada := convertido.get("input_tokens"):
                            convertido["input_tokens"] = max(0, numero_entrada - (convertido.get("cache_read_input_tokens") or 0))
                        linhas.append({"requestId": "r1", "timestamp": horario, "cwd": str(local),
                            "gitBranch": f"task/{task}", "message": {"model": modelo, "usage": convertido}})
                    else:
                        linhas.extend([
                            {"type": "session_meta", "timestamp": horario, "payload": {
                                "cwd": str(local), "model": modelo, "git": {"branch": f"task/{task}"}}},
                            {"type": "event_msg", "timestamp": horario, "payload": {
                                "type": "token_count", "info": {"total_token_usage": uso}}}])
                if agente == "claude":
                    gerador.shuffle(linhas)
                else:
                    blocos = [linhas[indice:indice + 2] for indice in range(0, len(linhas), 2)]
                    gerador.shuffle(blocos)
                    linhas = [linha for bloco in blocos for linha in bloco]
                arquivo = self.gravar(f"{agente}/a.jsonl", linhas)
                with patch("custo.subprocess.run", return_value=resultado_git):
                    codigo, texto, erro = self.rodar("--check-budget", str(principal),
                                                    "--since", "2026-11-17", "--json")
                grupo = json.loads(texto)["grupos"][0]
                self.assertEqual(grupo["task"], task)
                self.assertGreaterEqual(grupo["limite_superior_tokens"], real)
                self.assertGreaterEqual(grupo["limite_superior_minutos"], 2)
                if real > 400000:
                    self.assertEqual(codigo, 1, erro)
                arquivo.unlink()
        self.assertGreater(excedidos, 0)

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

    def test_kit_fim_inclui_duracao_ao_atravessar_meia_noite(self):
        self.gravar("kit/uso.jsonl", [{"data": "2026-11-16T23:59:00Z", "modelo": "m",
                    "entrada": 500000, "saida": 0, "duracao_segundos": 120,
                    "task": "BL-LU-3", "pasta": str(self.raiz)}])
        registros, avisos = custo.coletar()
        self.assertFalse(avisos)
        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["inicio"], custo.data("2026-11-16T23:59:00Z"))
        self.assertEqual(registros[0]["fim"], custo.data("2026-11-17T00:01:00Z"))
        self.assertEqual(registros[0]["minutos"], 2)

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
                codigo, saida, _ = self.rodar("--check-budget", str(self.raiz), "--json")
                self.assertEqual(codigo, esperado)
                self.assertEqual(bool(json.loads(saida)["estouros"]), bool(esperado))
        outro = self.raiz / "outro/.kit-ia/projeto.yaml"
        outro.parent.mkdir(parents=True)
        outro.write_text("orcamento:\n  por_task: {tokens: 0, minutos: 0}", encoding="utf-8")
        self.assertEqual(self.rodar("--check-budget", str(outro.parent.parent))[0], 0)

    def test_filtros_agrupamentos_e_lote_markdown(self):
        self.codex()
        for por, esperado in (("task", "BL-LU-3"), ("agente", "codex"), ("modelo", "modelo"), ("papel", "principal")):
            opcao = {"task": "task", "agente": "agent", "modelo": "model", "papel": "role"}[por]
            codigo, saida, _ = self.rodar("--since", "2026-11-16", "--by", opcao, "--json")
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(saida)["grupos"][0][por], esperado)
        self.assertEqual(json.loads(self.rodar("--since", "2026-11-17", "--json")[1])["grupos"], [])
        saida = self.rodar("--batch", "BL-LU-3,BL-LU-4")[1]
        self.assertIn("| BL-LU-3 | 110 | 3.00 | — |", saida)
        self.assertIn("Maior fonte de gasto: codex", saida)
        self.assertNotIn("BL-LU-3 |", self.rodar("--batch", "BL-LU-4")[1])

    def test_orcamento_inclui_worktrees_irmas_e_exclui_outro_projeto(self):
        principal = self.raiz / "projeto com espaços"
        worktree = self.raiz / "worktrees/BL-LU-3"
        outro = self.raiz / "outro"
        for raiz in (principal, worktree):
            configuracao = raiz / ".kit-ia/projeto.yaml"
            configuracao.parent.mkdir(parents=True)
            configuracao.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
        self.gravar("kit/uso.jsonl", [
            {"pasta": str(local), "task": task, "entrada": tokens, "saida": 0,
             "data": "2026-11-16T10:00:00Z", "duracao_segundos": 0}
            for local, task, tokens in ((worktree / "src", "BL-LU-3", 500000),
                                       (outro, "BL-LU-4", 900000))])
        saida_git = f"worktree {principal}\0HEAD a\0branch refs/heads/main\0\0worktree {worktree}\0HEAD b\0\0"
        resultado = subprocess.CompletedProcess([], 0, stdout=saida_git, stderr="")
        with patch("custo.subprocess.run", return_value=resultado) as executar:
            for caminho in (principal, worktree, principal / ".kit-ia/projeto.yaml"):
                with self.subTest(caminho=caminho):
                    codigo, saida, _ = self.rodar("--check-budget", str(caminho), "--json")
                    dados = json.loads(saida)
                    self.assertEqual(codigo, 1)
                    self.assertEqual([grupo["task"] for grupo in dados["grupos"]], ["BL-LU-3"])
                    self.assertEqual(dados["grupos"][0]["tokens"], 500000)
                    self.assertEqual(len(dados["estouros"]), 1)
            self.assertEqual(executar.call_args.args[0],
                             ["git", "-C", str(principal), "worktree", "list", "--porcelain", "-z"])

    def test_raizes_sem_git_e_subpasta_nao_incluem_outros_projetos(self):
        with patch("custo.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(custo.raizes_projeto(self.raiz), [self.raiz])
        resultado = subprocess.CompletedProcess([], 0, stdout=f"worktree {self.raiz}\0\0", stderr="")
        subpasta = self.raiz / "subprojeto"
        with patch("custo.subprocess.run", return_value=resultado):
            self.assertEqual(custo.raizes_projeto(subpasta), [subpasta])

    def test_erros_esperados_sem_stack_trace(self):
        self.assertEqual(self.rodar("--since", "ontem")[0], 1)
        projeto = self.raiz / "projeto.yaml"
        projeto.write_text("orcamento: |\n  errado", encoding="utf-8")
        codigo, _, erro = self.rodar("--check-budget", str(projeto))
        self.assertEqual(codigo, 1)
        self.assertIn("linha 1", erro)
        for conteudo in ("orcamento: {}", "orcamento: 1", "orcamento: {por_task: []}"):
            projeto.write_text(conteudo, encoding="utf-8")
            self.assertEqual(self.rodar("--check-budget", str(projeto))[0], 1)

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
    def test_preserva_espaco_antes_de_dois_pontos_no_valor(self):
        dados = custo.ler_yaml('''nome: antes :depois
mapa: {nome: antes :depois}
aspas: "antes: depois"
''')
        self.assertEqual(dados, {"nome": "antes :depois", "mapa": {"nome": "antes :depois"},
                                 "aspas": "antes: depois"})

    def test_rejeita_dois_pontos_estrutural_em_escalar_com_linha(self):
        for texto in ("nome: antes: depois", "mapa: {nome: antes: depois}",
                      "nomes:\n  - antes: depois"):
            with self.subTest(texto=texto), self.assertRaisesRegex(ValueError, "linha [12]:"):
                custo.ler_yaml(texto)

    def test_apostrofo_em_escalar_sem_aspas_e_aspas_delimitadoras(self):
        dados = custo.ler_yaml('''nome: D'Avila # comentário
lista: [D'Avila, "D'Avila # nome", 'D''Avila: nome']
mapa: {sobrenome: D'Avila}
nomes:
  - D'Avila
  - 'D''Avila # nome'
''')
        self.assertEqual(dados["nome"], "D'Avila")
        self.assertEqual(dados["lista"], ["D'Avila", "D'Avila # nome", "D'Avila: nome"])
        self.assertEqual(dados["mapa"], {"sobrenome": "D'Avila"})
        self.assertEqual(dados["nomes"], ["D'Avila", "D'Avila # nome"])
        for texto in ("nome: 'D'Avila", 'nome: "D\'Avila', "nomes:\n  - 'D'Avila"):
            with self.subTest(texto=texto), self.assertRaisesRegex(ValueError, "linha [12]:"):
                custo.ler_yaml(texto)

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
