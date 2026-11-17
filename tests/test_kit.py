"""Testes do kit.py. Rodar com: python -m unittest discover -s tests -v"""
import argparse
import contextlib
import io
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kit  # noqa: E402


def rodar(*argv: str) -> tuple[int, str, str]:
    """Roda o kit como na linha de comando e devolve (código de saída, stdout, stderr)."""
    saida, erro = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
        codigo = kit.main(list(argv))
    return codigo, saida.getvalue(), erro.getvalue()


def registrar_em_processo(base, perfil, iniciado, lido, continuar):
    """Coordena processos reais para manter a primeira transação aberta durante a segunda."""
    os.environ["KIT_IA_HOME"] = perfil
    carregar = kit.carregar_projetos

    def carregar_e_sinalizar():
        projetos = carregar()
        lido.set()
        if continuar is not None and not continuar.wait(10):
            raise RuntimeError("a transação não foi liberada pelo teste")
        return projetos

    iniciado.set()
    with unittest.mock.patch.object(kit, "carregar_projetos", side_effect=carregar_e_sinalizar):
        kit.registrar_projeto(Path(base), ["universal"], None, True)


class CustoTest(unittest.TestCase):
    def test_orcamento_recusa_filtro_de_outro_projeto_sem_ocultar_estouro(self):
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = Path(temporaria)
            projeto = raiz / "projeto-a"
            outro = raiz / "projeto-b"
            projeto.mkdir()
            outro.mkdir()
            configuracao = projeto / ".kit-ia/projeto.yaml"
            configuracao.parent.mkdir()
            configuracao.write_text("orcamento: {por_task: {tokens: 100, minutos: 30}}", encoding="utf-8")
            inicio = kit.custo.data("2026-11-17")
            registro = kit.custo.registro("codex", "modelo", "executor", str(projeto), "BL-LU-5",
                                          inicio, inicio, {"entrada": 1000, "saida": 0})
            with unittest.mock.patch.object(kit.custo, "coletar", return_value=([registro], [])):
                for filtro in (None, projeto, configuracao, outro):
                    with self.subTest(filtro=filtro):
                        opcoes = ["--project", str(filtro)] if filtro else []
                        codigo, saida, erro = rodar("cost", "--check-budget", str(configuracao),
                                                  *opcoes, "--json")
                        self.assertEqual(codigo, 1)
                        if filtro == outro:
                            self.assertIn("--project e --check-budget devem indicar o mesmo projeto", erro)
                        else:
                            self.assertEqual(json.loads(saida)["grupos"][0]["tokens"], 1000)
                            self.assertTrue(json.loads(saida)["estouros"])

    def test_alias_cost_check_budget_recusa_medicao_incompleta(self):
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = Path(temporaria)
            (raiz / "projeto.yaml").write_text("orcamento: {por_task: {tokens: 400000, minutos: 30}}", encoding="utf-8")
            item = kit.custo.registro("codex", "modelo", "principal", str(raiz), "task/BL-LU-3",
                kit.custo.data("2026-11-17"), kit.custo.data("2026-11-17"),
                {"entrada": 1, "saida": 1}, medicao_incompleta=True)
            with unittest.mock.patch("kit.custo.coletar", return_value=([item], [])):
                codigo, saida, _ = rodar("cost", "--check-budget", str(raiz / "projeto.yaml"), "--json")
            dados = json.loads(saida)
            self.assertEqual(codigo, 1)
            self.assertEqual(dados["estouros"], [])
            self.assertEqual(dados["incompletas"], ["BL-LU-3: medição incompleta"])

    def test_claude_atualizacao_desconhecida_preserva_estouro_da_mesma_resposta(self):
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = Path(temporaria)
            projeto = raiz / ".kit-ia/projeto.yaml"
            projeto.parent.mkdir()
            projeto.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
            fonte = raiz / "claude/a.jsonl"
            fonte.parent.mkdir()
            ambiente = {"KIT_IA_HOME": str(raiz / "kit"), "KIT_IA_CLAUDE_DIR": str(fonte.parent),
                        "KIT_IA_CODEX_DIR": str(raiz / "codex"),
                        "KIT_IA_ANTIGRAVITY_DIR": str(raiz / "antigravity")}
            linhas = []
            with unittest.mock.patch.dict(os.environ, ambiente):
                for indice, entrada, saida_tokens in ((0, 500000, 10), (1, None, 11)):
                    with self.subTest(atualizacao=indice):
                        linhas.append({"requestId": "r1", "timestamp": f"2026-11-16T10:0{indice}:00Z",
                                       "cwd": str(raiz), "gitBranch": "task/BL-LU-3", "message": {
                                       "model": "modelo", "usage": {
                                       "input_tokens": entrada, "output_tokens": saida_tokens}}})
                        fonte.write_text("\n".join(json.dumps(linha) for linha in linhas), encoding="utf-8")
                        codigo, saida, erro = rodar("cost", "--check-budget", str(raiz), "--json")
                        self.assertEqual(codigo, 1, erro)
                        dados = json.loads(saida)
                        self.assertEqual(len(dados["grupos"]), 1)
                        grupo = dados["grupos"][0]
                        self.assertEqual(grupo["tokens"], 500000 + saida_tokens)
                        self.assertEqual(grupo["parcial"], bool(indice))
                        self.assertIsNone(grupo["custo_usd"])
                        self.assertEqual(len(dados["estouros"]), 1)
                        self.assertIn(f"BL-LU-3: tokens {500000 + saida_tokens}.00 > 400000",
                                      dados["estouros"][0])

    def test_claude_resposta_parcial_preserva_estouro_comprovado(self):
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = Path(temporaria)
            projeto = raiz / ".kit-ia/projeto.yaml"
            projeto.parent.mkdir()
            projeto.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
            fonte = raiz / "claude/a.jsonl"
            fonte.parent.mkdir()
            ambiente = {"KIT_IA_HOME": str(raiz / "kit"),
                        "KIT_IA_CLAUDE_DIR": str(fonte.parent),
                        "KIT_IA_CODEX_DIR": str(raiz / "codex"),
                        "KIT_IA_ANTIGRAVITY_DIR": str(raiz / "antigravity")}
            linhas = [{"requestId": f"r{indice}", "cwd": str(raiz), "gitBranch": "task/BL-LU-3",
                       "message": {"model": "falso", "usage": uso}} for indice, uso in enumerate([
                       {"input_tokens": 500000, "output_tokens": 10},
                       {"input_tokens": None, "output_tokens": 1}])]
            with unittest.mock.patch.dict(os.environ, ambiente):
                for ordem in (linhas, list(reversed(linhas))):
                    with self.subTest(parcial_primeiro=ordem[0]["requestId"] == "r1"):
                        fonte.write_text("\n".join(json.dumps(linha) for linha in ordem) + "\n", encoding="utf-8")
                        codigo, saida, erro = rodar("cost", "--check-budget", str(raiz), "--json")
                        self.assertEqual(codigo, 1, erro)
                        dados = json.loads(saida)
                        self.assertEqual(len(dados["grupos"]), 1)
                        grupo = dados["grupos"][0]
                        self.assertEqual((grupo["entrada"], grupo["saida"], grupo["tokens"]), (500000, 11, 500011))
                        self.assertTrue(grupo["parcial"])
                        self.assertIsNone(grupo["custo_usd"])
                        self.assertEqual(len(dados["estouros"]), 1)
                        self.assertIn("BL-LU-3: tokens 500011.00 > 400000", dados["estouros"][0])

    def test_claude_uso_atualizado_revela_estouro_do_orcamento(self):
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = Path(temporaria)
            projeto = raiz / ".kit-ia/projeto.yaml"
            projeto.parent.mkdir()
            projeto.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
            fonte = raiz / "claude/a.jsonl"
            fonte.parent.mkdir()
            ambiente = {"KIT_IA_HOME": str(raiz / "kit"),
                        "KIT_IA_CLAUDE_DIR": str(fonte.parent),
                        "KIT_IA_CODEX_DIR": str(raiz / "codex"),
                        "KIT_IA_ANTIGRAVITY_DIR": str(raiz / "antigravity")}
            linhas = []
            with unittest.mock.patch.dict(os.environ, ambiente):
                for saida_tokens, total, esperado in ((35, 399035, 0), (4359, 403359, 1),
                                                     (4359, 403359, 1)):
                    with self.subTest(saida_tokens=saida_tokens, repeticoes=len(linhas)):
                        linhas.append({"requestId": "r1", "timestamp": "2026-11-16T10:00:00Z",
                                       "cwd": str(raiz), "gitBranch": "task/BL-LU-3", "message": {
                                       "id": "m1", "model": "falso", "usage": {
                                       "input_tokens": 399000, "output_tokens": saida_tokens}}})
                        fonte.write_text("\n".join(json.dumps(linha) for linha in linhas) + "\n",
                                         encoding="utf-8")
                        codigo, saida, erro = rodar("cost", "--check-budget", str(raiz), "--json")
                        self.assertEqual(codigo, esperado, erro)
                        dados = json.loads(saida)
                        self.assertEqual(len(dados["grupos"]), 1)
                        self.assertEqual(dados["grupos"][0]["tokens"], total)
                        self.assertEqual(len(dados["estouros"]), esperado)
                        if esperado:
                            self.assertIn("BL-LU-3: tokens 403359.00 > 400000", dados["estouros"][0])

    def test_desde_preserva_chamada_que_atravessa_data_e_estouro_do_orcamento(self):
        with tempfile.TemporaryDirectory() as temporaria:
            raiz = Path(temporaria)
            projeto = raiz / ".kit-ia/projeto.yaml"
            projeto.parent.mkdir()
            projeto.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
            ambiente = {"KIT_IA_HOME": str(raiz),
                        "KIT_IA_CLAUDE_DIR": str(raiz / "claude"),
                        "KIT_IA_CODEX_DIR": str(raiz / "codex"),
                        "KIT_IA_ANTIGRAVITY_DIR": str(raiz / "antigravity")}
            with unittest.mock.patch.dict(os.environ, ambiente):
                for duracao, desde, incluido in ((120, None, True), (120, "2026-11-17", True),
                                                (60, "2026-11-17", True), (59, "2026-11-17", False),
                                                (120, "2026-11-18", False)):
                    with self.subTest(duracao=duracao, desde=desde):
                        (raiz / "uso.jsonl").write_text(json.dumps({
                            "data": "2026-11-16T23:59:00Z", "duracao_segundos": duracao,
                            "modelo": "falso", "entrada": 500000, "saida": 0,
                            "task": "BL-LU-3", "pasta": str(raiz)}) + "\n", encoding="utf-8")
                        filtros = ["--since", desde] if desde else []
                        codigo, saida, erro = rodar("cost", *filtros, "--json")
                        self.assertEqual(codigo, 0, erro)
                        dados = json.loads(saida)
                        if incluido:
                            self.assertEqual(len(dados["grupos"]), 1)
                            self.assertEqual(dados["grupos"][0]["tokens"], 500000)
                            self.assertEqual(dados["grupos"][0]["minutos"], duracao / 60)
                        else:
                            self.assertEqual(dados["grupos"], [])
                        codigo, saida, erro = rodar("cost", *filtros, "--check-budget",
                                                   str(raiz), "--json")
                        self.assertEqual(codigo, int(incluido), erro)
                        orcamento = json.loads(saida)
                        self.assertEqual(orcamento["grupos"], dados["grupos"])
                        self.assertEqual(len(orcamento["estouros"]), int(incluido))
                        if incluido:
                            self.assertIn("BL-LU-3: tokens 500000.00 > 400000", orcamento["estouros"][0])


class ProjetoYamlTest(unittest.TestCase):
    def test_orcamento_rejeita_yaml_invalido_sem_traceback(self):
        with tempfile.TemporaryDirectory() as temporaria:
            projeto = Path(temporaria) / "projeto.yaml"
            projeto.write_text("nome: antes: depois\norcamento: {por_task: {tokens: 400000, minutos: 30}}",
                               encoding="utf-8")
            with unittest.mock.patch("kit.custo.coletar", return_value=([], [])):
                codigo, _, erro = rodar("cost", "--check-budget", str(projeto))
            self.assertEqual(codigo, 1)
            self.assertIn("linha 1:", erro)
            self.assertNotIn("Traceback", erro)
            projeto.write_text("nome: antes :depois", encoding="utf-8")
            self.assertEqual(kit.ler_projeto(projeto)["nome"], "antes :depois")


class FrontmatterTest(unittest.TestCase):
    def test_le_chaves_e_corpo(self):
        dados, corpo = kit.ler_frontmatter("---\nname: x\ndescription: \"faz y\"\n---\n\n# Corpo\n")
        self.assertEqual(dados, {"name": "x", "description": "faz y"})
        self.assertEqual(corpo, "# Corpo")

    def test_ignora_linhas_indentadas(self):
        dados, _ = kit.ler_frontmatter("---\nname: x\nmetadata:\n  autor: eu\n---\ncorpo")
        self.assertNotIn("autor", dados)

    def test_sem_fechamento_e_erro(self):
        with self.assertRaises(kit.ErroKit):
            kit.ler_frontmatter("---\nname: x\n")

    def test_sem_frontmatter_e_erro(self):
        with self.assertRaises(kit.ErroKit):
            kit.ler_frontmatter("# só corpo")


class ValidarTest(unittest.TestCase):
    def test_skills_do_kit_sao_validas(self):
        pastas = kit.pastas_de_skills()
        self.assertGreaterEqual(len(pastas), 5)
        for pasta in pastas:
            with self.subTest(skill=pasta.name):
                self.assertEqual(kit.problemas_da_skill(pasta), [])

    def test_detecta_nome_diferente_da_pasta(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "minha-skill"
            pasta.mkdir()
            (pasta / "SKILL.md").write_text("---\nname: outra\ndescription: d\n---\ncorpo", encoding="utf-8")
            self.assertIn("igual ao nome da pasta", kit.problemas_da_skill(pasta)[0])

    def test_detecta_descricao_longa_e_corpo_vazio(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "s"
            pasta.mkdir()
            (pasta / "SKILL.md").write_text(f"---\nname: s\ndescription: {'a' * 1100}\n---\n", encoding="utf-8")
            problemas = kit.problemas_da_skill(pasta)
            self.assertEqual(len(problemas), 2)

    def test_comando_validar_passa(self):
        codigo, saida, _ = rodar("validate")
        self.assertEqual(codigo, 0, saida)

    def test_links_quebrados(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "processo").mkdir()
            (raiz / "processo/existe.md").write_text("ok", encoding="utf-8")
            (raiz / "processo/a.md").write_text(
                "[bom](existe.md) [com âncora](existe.md#secao) [externo](https://x.com) [ancora](#local)\n"
                "[ruim](nao-existe.md)\n```\n[em bloco de código](ignorado.md)\n```\n",
                encoding="utf-8",
            )
            self.assertEqual(kit.links_quebrados(raiz), ["processo/a.md: link quebrado -> nao-existe.md"])

    def test_documentacao_do_kit_sem_links_quebrados(self):
        self.assertEqual(kit.links_quebrados(kit.RAIZ), [])

    def test_mcp_invalido_falha_a_validacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "mcp.json"
            arquivo.write_text(json.dumps({"servidores": {"x": {"tipo": "http"}}}), encoding="utf-8")
            with unittest.mock.patch.object(kit, "ARQUIVO_MCP", arquivo):
                codigo, _, erro = rodar("validate")
        self.assertEqual(codigo, 1)
        self.assertIn("precisa de 'url'", erro)

    def test_listar_e_versao(self):
        codigo, saida, _ = rodar("list")
        self.assertEqual(codigo, 0)
        self.assertIn("verificar", saida)
        with self.assertRaises(SystemExit) as fim, contextlib.redirect_stdout(io.StringIO()) as saida:
            kit.main(["--version"])
        self.assertEqual(fim.exception.code, 0)
        self.assertIn(kit.VERSAO, saida.getvalue())


class ConverterServidorTest(unittest.TestCase):
    HTTP = {"tipo": "http", "url": "https://x/mcp"}
    STDIO = {"tipo": "stdio", "comando": "npx", "args": ["-y", "pacote"], "env": {"K": "${K}"}}

    def test_http_em_cada_formato(self):
        self.assertEqual(kit.converter_servidor("claude", self.HTTP), {"type": "http", "url": "https://x/mcp"})
        self.assertEqual(kit.converter_servidor("vscode", self.HTTP), {"type": "http", "url": "https://x/mcp"})
        self.assertEqual(kit.converter_servidor("cursor", self.HTTP), {"url": "https://x/mcp"})
        self.assertEqual(kit.converter_servidor("gemini", self.HTTP), {"httpUrl": "https://x/mcp"})
        self.assertEqual(kit.converter_servidor("opencode", self.HTTP),
                         {"type": "remote", "url": "https://x/mcp", "enabled": True})

    def test_stdio_em_cada_formato(self):
        esperado = {"command": "npx", "args": ["-y", "pacote"], "env": {"K": "${K}"}}
        self.assertEqual(kit.converter_servidor("claude", self.STDIO), {"type": "stdio", **esperado})
        self.assertEqual(kit.converter_servidor("cursor", self.STDIO), esperado)
        self.assertEqual(kit.converter_servidor("opencode", self.STDIO),
                         {"type": "local", "command": ["npx", "-y", "pacote"], "enabled": True,
                          "environment": {"K": "${K}"}})

    def test_cabecalhos_em_cada_formato(self):
        com_cabecalho = {**self.HTTP, "cabecalhos": {"Authorization": "Bearer ${TOKEN}"}}
        esperado = {"Authorization": "Bearer ${TOKEN}"}
        self.assertEqual(kit.converter_servidor("claude", com_cabecalho)["headers"], esperado)
        self.assertEqual(kit.converter_servidor("gemini", com_cabecalho)["headers"], esperado)
        self.assertEqual(kit.converter_servidor("opencode", com_cabecalho)["headers"], esperado)

    def test_formato_desconhecido_e_erro(self):
        with self.assertRaises(kit.ErroKit):
            kit.converter_servidor("xpto", self.HTTP)


class ComandosMcpGlobalTest(unittest.TestCase):
    def test_http_para_os_dois_agentes(self):
        servidores = {"context7": {"tipo": "http", "url": "https://mcp.context7.com/mcp"}}
        self.assertEqual(kit.comandos_mcp_global("comando-codex", servidores), [
            ["codex", "mcp", "add", "context7", "--url", "https://mcp.context7.com/mcp"]])
        self.assertEqual(kit.comandos_mcp_global("comando-antigravity", servidores), [
            ["agy", "mcp", "add", "context7", "https://mcp.context7.com/mcp"]])

    def test_stdio_com_env_para_os_dois_agentes(self):
        servidores = {"local": {"tipo": "stdio", "comando": "npx", "args": ["-y", "meu pacote"],
                                "env": {"K": "${K}", "OUTRA": "valor com espaço"}}}
        env = ["--env", "K=${K}", "--env", "OUTRA=valor com espaço"]
        self.assertEqual(kit.comandos_mcp_global("comando-codex", servidores), [
            ["codex", "mcp", "add", "local", *env, "--", "npx", "-y", "meu pacote"]])
        self.assertEqual(kit.comandos_mcp_global("comando-antigravity", servidores), [
            ["agy", "mcp", "add", *env, "local", "--", "npx", "-y", "meu pacote"]])

    def test_antigravity_cabecalhos_e_env_antes_do_nome(self):
        servidores = {"remoto": {"tipo": "http", "url": "https://x/mcp",
                                 "cabecalhos": {"X-Cliente": "kit ia", "X-Versao": "1"},
                                 "env": {"K": "${K}"}}}
        self.assertEqual(kit.comandos_mcp_global("comando-antigravity", servidores), [[
            "agy", "mcp", "add", "--header", "X-Cliente: kit ia", "--header", "X-Versao: 1",
            "--env", "K=${K}", "remoto", "https://x/mcp"]])
        self.assertEqual(kit.comandos_mcp_global("comando-codex", servidores), [])

    def test_um_comando_por_servidor_sem_mutar_entrada(self):
        servidores = {"um": {"tipo": "http", "url": "https://x/mcp"},
                      "dois": {"tipo": "stdio", "comando": "servidor"}}
        original = json.dumps(servidores)
        self.assertEqual(kit.comandos_mcp_global("comando-codex", servidores), [
            ["codex", "mcp", "add", "um", "--url", "https://x/mcp"],
            ["codex", "mcp", "add", "dois", "--", "servidor"]])
        self.assertEqual(json.dumps(servidores), original)

    def test_formato_desconhecido_e_erro(self):
        with self.assertRaises(kit.ErroKit):
            kit.comandos_mcp_global("comando-xpto", {})

    def test_comando_legivel_preserva_espacos_e_metacaracteres(self):
        comando = ["agy", "mcp", "add", "--env", "K=${K}", "--header", "X: d'agua & a"]
        with unittest.mock.patch.object(kit.os, "name", "nt"):
            self.assertEqual(kit.comando_legivel(comando),
                             "agy mcp add --env 'K=${K}' --header 'X: d''agua & a'")
        with unittest.mock.patch.object(kit.os, "name", "posix"):
            self.assertEqual(kit.shlex.split(kit.comando_legivel(comando)), comando)

    def test_executavel_do_path_tem_prioridade(self):
        with unittest.mock.patch.object(kit.shutil, "which", return_value="/bin/codex") as busca:
            self.assertEqual(kit.localizar_executavel("codex", []), "/bin/codex")
        busca.assert_called_once_with("codex")

    def test_executaveis_alternativos_da_configuracao(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            agy = raiz / ".gemini/bin/agy.exe"
            codex = raiz / "OpenAI/Codex/bin/0.167/codex.exe"
            for arquivo in (agy, codex):
                arquivo.parent.mkdir(parents=True)
                arquivo.write_text("falso", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"HOME": tmp, "USERPROFILE": tmp, "LOCALAPPDATA": tmp}), \
                    unittest.mock.patch.object(kit.shutil, "which", return_value=None):
                for agente, executavel, esperado in (("codex", "codex", codex), ("antigravity", "agy", agy)):
                    with self.subTest(agente=agente):
                        alternativas = kit.carregar_agentes()[agente]["mcp"]["executaveis_alternativos"]
                        self.assertEqual(Path(kit.localizar_executavel(executavel, alternativas)), esperado)
                self.assertIsNone(kit.localizar_executavel("ausente", [str(raiz / "ausente")]))


class InstalarTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.projeto = Path(self._tmp.name)
        registro = tempfile.TemporaryDirectory()
        self.addCleanup(registro.cleanup)
        ambiente = unittest.mock.patch.dict(os.environ, {"KIT_IA_HOME": str(Path(registro.name) / "kit")})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        # Guarda de todos os testes de instalação: nenhum teste pode chamar a CLI real.
        executar = unittest.mock.patch.object(kit.subprocess, "run")
        self.executar = executar.start()
        self.addCleanup(executar.stop)
        self.executar.return_value.returncode = 0
        perguntar = unittest.mock.patch("builtins.input", return_value="n")
        self.perguntar = perguntar.start()
        self.addCleanup(perguntar.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def ler_json(self, relativo: str) -> dict:
        return json.loads((self.projeto / relativo).read_text(encoding="utf-8"))

    def test_projeto_vazio_recebe_tudo(self):
        codigo, saida, erro = rodar("install", str(self.projeto))
        self.assertEqual(codigo, 0, erro)
        for skill in ("verificar", "planejar", "revisar", "criar-skill", "iniciar-agents-md"):
            self.assertTrue((self.projeto / ".agents/skills" / skill / "SKILL.md").is_file())
            self.assertTrue((self.projeto / ".claude/skills" / skill / "SKILL.md").is_file())
        self.assertTrue((self.projeto / ".claude/skills/iniciar-agents-md/modelo-AGENTS.md").is_file())
        self.assertIn("## Arquitetura (não quebrar)", (self.projeto / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertTrue((self.projeto / "CLAUDE.md").read_text(encoding="utf-8").startswith("@AGENTS.md"))
        self.assertIn("context7", self.ler_json(".mcp.json")["mcpServers"])
        self.assertIn("context7", self.ler_json(".cursor/mcp.json")["mcpServers"])
        self.assertIn("context7", self.ler_json(".vscode/mcp.json")["servers"])
        self.assertEqual(self.ler_json("opencode.json")["mcp"]["context7"]["type"], "remote")
        gemini = self.ler_json(".gemini/settings.json")
        self.assertIn("AGENTS.md", gemini["context"]["fileName"])
        self.assertFalse((self.projeto / ".codex").exists())
        self.assertIn("MCP global (rode uma vez):", saida)
        self.assertIn("codex mcp add context7 --url https://mcp.context7.com/mcp", saida)
        self.assertIn("agy mcp add context7 https://mcp.context7.com/mcp", saida)
        self.executar.assert_not_called()
        self.perguntar.assert_not_called()

        kit_ia = self.projeto / ".kit-ia"
        self.assertTrue((kit_ia / "processo/00-nucleo.md").is_file())
        self.assertTrue((kit_ia / "padroes/README.md").is_file())
        self.assertTrue((kit_ia / "modelos/tarefa.md").is_file())
        self.assertTrue((kit_ia / "modelos/ci/azure-pipelines.yml").is_file())
        self.assertEqual((kit_ia / "VERSAO").read_text(encoding="utf-8").strip(), kit.VERSAO)
        projeto_yaml = (kit_ia / "projeto.yaml").read_text(encoding="utf-8")
        self.assertIn(f"nome: {self.projeto.name}", projeto_yaml)
        self.assertIn(kit.REFERENCIA_NUCLEO, (self.projeto / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("0 aviso(s)", saida)

    def test_segunda_instalacao_nao_muda_nada(self):
        rodar("install", str(self.projeto))
        codigo, saida, _ = rodar("install", str(self.projeto))
        self.assertEqual(codigo, 0)
        self.assertIn("0 mudança(s)", saida)

    def test_simular_nao_escreve(self):
        codigo, saida, _ = rodar("install", str(self.projeto), "--dry-run")
        self.assertEqual(codigo, 0)
        self.assertIn("[simulação]", saida)
        self.assertEqual(list(self.projeto.iterdir()), [])

    def test_filtra_agentes_e_skills(self):
        rodar("install", str(self.projeto), "--agents", "claude", "--skills", "verificar")
        self.assertTrue((self.projeto / ".claude/skills/verificar").is_dir())
        self.assertFalse((self.projeto / ".claude/skills/planejar").exists())
        self.assertFalse((self.projeto / ".agents").exists())
        self.assertFalse((self.projeto / ".cursor").exists())

    def test_preserva_arquivos_do_usuario(self):
        (self.projeto / "AGENTS.md").write_text("meu agents", encoding="utf-8")
        (self.projeto / "CLAUDE.md").write_text("meu claude", encoding="utf-8")
        propria = self.projeto / ".claude/skills/verificar"
        propria.mkdir(parents=True)
        (propria / "SKILL.md").write_text("minha skill", encoding="utf-8")
        (self.projeto / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "tarefas": {"type": "http", "url": "http://localhost:8080/mcp"},
            "context7": {"type": "http", "url": "https://outro"},
        }}), encoding="utf-8")

        codigo, saida, _ = rodar("install", str(self.projeto), "--agents", "claude")

        self.assertEqual(codigo, 0)
        self.assertEqual((self.projeto / "AGENTS.md").read_text(encoding="utf-8"), "meu agents")
        self.assertEqual((propria / "SKILL.md").read_text(encoding="utf-8"), "minha skill")
        servidores = self.ler_json(".mcp.json")["mcpServers"]
        self.assertEqual(servidores["tarefas"]["url"], "http://localhost:8080/mcp")
        self.assertEqual(servidores["context7"]["url"], "https://outro")
        self.assertIn("não importa o AGENTS.md", saida)
        self.assertIn("não foi instalada pelo kit", saida)

    def test_reinstalar_atualiza_skill_do_kit(self):
        rodar("install", str(self.projeto), "--agents", "claude")
        copia = self.projeto / ".claude/skills/verificar/SKILL.md"
        copia.write_text("editada à mão", encoding="utf-8")
        rodar("install", str(self.projeto), "--agents", "claude")
        self.assertEqual(copia.read_text(encoding="utf-8"),
                         (kit.PASTA_SKILLS / "verificar/SKILL.md").read_text(encoding="utf-8"))

    def test_preserva_projeto_yaml_e_restaura_processo(self):
        rodar("install", str(self.projeto), "--agents", "claude")
        projeto_yaml = self.projeto / ".kit-ia/projeto.yaml"
        projeto_yaml.write_text("meu projeto.yaml", encoding="utf-8")
        nucleo = self.projeto / ".kit-ia/processo/00-nucleo.md"
        nucleo.write_text("editado à mão", encoding="utf-8")

        rodar("install", str(self.projeto), "--agents", "claude")

        self.assertEqual(projeto_yaml.read_text(encoding="utf-8"), "meu projeto.yaml")
        self.assertEqual(nucleo.read_text(encoding="utf-8"),
                         (kit.RAIZ / "processo/00-nucleo.md").read_text(encoding="utf-8"))

    def test_avisa_agents_md_que_nao_aponta_o_processo(self):
        (self.projeto / "AGENTS.md").write_text("# Meu projeto\n", encoding="utf-8")
        _, saida, _ = rodar("install", str(self.projeto), "--agents", "universal")
        self.assertIn("não aponta o processo", saida)

    def test_forcar_substitui_skill_e_servidor_do_usuario(self):
        propria = self.projeto / ".claude/skills/verificar"
        propria.mkdir(parents=True)
        (propria / "SKILL.md").write_text("minha skill", encoding="utf-8")
        (self.projeto / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "context7": {"type": "http", "url": "https://outro"}}}), encoding="utf-8")

        rodar("install", str(self.projeto), "--agents", "claude", "--force")

        self.assertEqual((propria / "SKILL.md").read_text(encoding="utf-8"),
                         (kit.PASTA_SKILLS / "verificar/SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(self.ler_json(".mcp.json")["mcpServers"]["context7"]["url"], "https://mcp.context7.com/mcp")

    def test_preserva_toml_do_codex_existente(self):
        toml = self.projeto / ".codex/config.toml"
        toml.parent.mkdir()
        toml.write_text('model = "x"\n\n[mcp_servers.meu]\nurl = "http://localhost:9000/mcp"\n', encoding="utf-8")

        rodar("install", str(self.projeto), "--agents", "codex")
        rodar("install", str(self.projeto), "--agents", "codex")

        self.assertEqual(toml.read_text(encoding="utf-8"),
                         'model = "x"\n\n[mcp_servers.meu]\nurl = "http://localhost:9000/mcp"\n')

    def test_codex_e_antigravity_sozinhos_instalam_skills(self):
        for agente in ("codex", "antigravity"):
            with self.subTest(agente=agente):
                projeto = self.projeto / agente
                projeto.mkdir()
                codigo, _, erro = rodar("install", str(projeto), "--agents", agente)
                self.assertEqual(codigo, 0, erro)
                self.assertTrue((projeto / ".agents/skills/verificar/SKILL.md").is_file())
                self.assertFalse((projeto / ".codex").exists())
                self.assertFalse((projeto / ".gemini").exists())

    def test_cabecalho_codex_vira_aviso_sem_comando(self):
        servidores = {"com-header": {"tipo": "http", "url": "https://x/mcp",
                                     "cabecalhos": {"X-Cliente": "kit"}},
                      "sem-header": {"tipo": "http", "url": "https://y/mcp"}}
        with unittest.mock.patch.object(kit, "carregar_servidores", return_value=servidores):
            codigo, saida, erro = rodar("install", str(self.projeto), "--agents", "codex")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("configure à mão", saida)
        self.assertIn("1 aviso(s)", saida)
        self.assertNotIn("mcp add com-header", saida)
        self.assertIn("mcp add sem-header", saida)

    def test_mcp_global_exige_flag_mesmo_com_resposta_s(self):
        self.perguntar.return_value = "s"
        rodar("install", str(self.projeto))
        self.perguntar.assert_not_called()
        self.executar.assert_not_called()

    def test_mcp_global_confirmado_executa_argumentos_sem_shell(self):
        self.perguntar.return_value = "s"
        with unittest.mock.patch.object(kit.shutil, "which", side_effect=lambda nome: f"/bin/{nome}"):
            codigo, _, erro = rodar("install", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.perguntar.assert_called_once_with("Executar estes comandos? [s/N] ")
        self.assertEqual(self.executar.call_args_list, [
            unittest.mock.call(["/bin/codex", "mcp", "add", "context7", "--url", "https://mcp.context7.com/mcp"], check=False),
            unittest.mock.call(["/bin/agy", "mcp", "add", "context7", "https://mcp.context7.com/mcp"], check=False)])

    def test_mcp_global_recusado_nao_executa(self):
        for resposta in ("n", "", "sim"):
            with self.subTest(resposta=resposta):
                self.perguntar.return_value = resposta
                rodar("install", str(self.projeto), "--mcp-global")
                self.executar.assert_not_called()

    def test_mcp_global_sem_entrada_nao_executa(self):
        self.perguntar.side_effect = EOFError
        codigo, _, erro = rodar("install", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.executar.assert_not_called()

    def test_mcp_global_simulado_nao_pergunta_nem_executa(self):
        self.perguntar.return_value = "s"
        codigo, saida, erro = rodar("install", str(self.projeto), "--mcp-global", "--dry-run")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("MCP global (rode uma vez):", saida)
        self.assertEqual(list(self.projeto.iterdir()), [])
        self.perguntar.assert_not_called()
        self.executar.assert_not_called()

    def test_sem_mcp_omite_comandos_e_confirmacao(self):
        _, saida, _ = rodar("install", str(self.projeto), "--mcp-global", "--no-mcp")
        self.assertNotIn("mcp add", saida)
        self.perguntar.assert_not_called()
        self.executar.assert_not_called()

    def test_mcp_global_executavel_ausente_vira_aviso(self):
        self.perguntar.return_value = "s"
        with unittest.mock.patch.object(kit.shutil, "which", return_value=None), \
                unittest.mock.patch.object(kit.glob, "glob", return_value=[]):
            codigo, saida, erro = rodar("install", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("codex não encontrado", saida)
        self.assertIn("agy não encontrado", saida)
        self.executar.assert_not_called()

    def test_mcp_global_falha_vira_aviso_e_continua(self):
        self.perguntar.return_value = "s"
        self.executar.side_effect = [unittest.mock.Mock(returncode=7), unittest.mock.Mock(returncode=0)]
        with unittest.mock.patch.object(kit.shutil, "which", side_effect=lambda nome: nome):
            codigo, saida, erro = rodar("install", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("codex falhou com código de saída 7", saida)
        self.assertEqual(self.executar.call_count, 2)

    def test_mcp_global_erro_ao_iniciar_vira_aviso(self):
        self.perguntar.return_value = "s"
        self.executar.side_effect = OSError("executável indisponível")
        with unittest.mock.patch.object(kit.shutil, "which", return_value="codex"):
            codigo, saida, erro = rodar("install", str(self.projeto), "--agents", "codex", "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("não foi possível executar codex", saida)

    def test_mescla_settings_do_gemini_existente(self):
        settings = self.projeto / ".gemini/settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"theme": "escuro", "context": {"fileName": "GEMINI.md"}}), encoding="utf-8")

        rodar("install", str(self.projeto), "--agents", "gemini")

        dados = self.ler_json(".gemini/settings.json")
        self.assertEqual(dados["theme"], "escuro")
        self.assertEqual(dados["context"]["fileName"], "GEMINI.md")  # escolha do usuário mantida
        self.assertIn("context7", dados["mcpServers"])

    def test_json_invalido_vira_mensagem(self):
        (self.projeto / ".mcp.json").write_text("{ // comentário\n}", encoding="utf-8")
        codigo, _, erro = rodar("install", str(self.projeto), "--agents", "claude")
        self.assertEqual(codigo, 1)
        self.assertIn("não é um JSON válido", erro)

    def test_destino_inexistente_e_erro(self):
        codigo, _, erro = rodar("install", str(self.projeto / "nao-existe"))
        self.assertEqual(codigo, 1)
        self.assertIn("não existe", erro)


class AtualizarProjetosTest(unittest.TestCase):
    def setUp(self):
        temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(temporaria.cleanup)
        self.raiz = Path(temporaria.name)
        self.projeto = self.raiz / "projeto com espaços"
        self.projeto.mkdir()
        self.registro = self.raiz / "perfil/projetos.json"
        ambiente = unittest.mock.patch.dict(os.environ, {"KIT_IA_HOME": str(self.registro.parent)})
        ambiente.start()
        self.addCleanup(ambiente.stop)

    def instalar(self, projeto=None, *opcoes):
        codigo, _, erro = rodar("install", str(projeto or self.projeto), "--agents", "claude,universal", *opcoes)
        self.assertEqual(codigo, 0, erro)

    def registros(self):
        return json.loads(self.registro.read_text(encoding="utf-8"))

    def snapshot(self):
        return {p.relative_to(self.raiz).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.raiz.rglob("*") if p.is_file()}

    def test_registra_caminho_absoluto_agentes_versao_data_sem_duplicar(self):
        self.instalar()
        self.instalar()
        registros = self.registros()
        self.assertEqual(list(registros), [str(self.projeto.resolve())])
        dados = registros[str(self.projeto.resolve())]
        self.assertEqual(dados["agentes"], ["claude", "universal"])
        self.assertEqual(dados["versao"], kit.VERSAO)
        self.assertIsNotNone(kit.custo.data(dados["data"]))
        codigo, _, erro = rodar("install", str(self.projeto), "--agents", "universal")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(self.registros()[str(self.projeto.resolve())]["agentes"], ["universal"])

    def test_registros_concorrentes_preservam_ambos_projetos(self):
        contexto = multiprocessing.get_context("spawn")
        continuar = contexto.Event()
        iniciados = [contexto.Event(), contexto.Event()]
        lidos = [contexto.Event(), contexto.Event()]
        caminhos = [self.projeto, self.raiz / "outro"]
        processos = [contexto.Process(target=registrar_em_processo, args=(
            str(caminho), str(self.registro.parent), iniciados[indice], lidos[indice],
            continuar if indice == 0 else None)) for indice, caminho in enumerate(caminhos)]
        try:
            processos[0].start()
            self.assertTrue(lidos[0].wait(10), "o primeiro processo não leu o registro")
            processos[1].start()
            self.assertTrue(iniciados[1].wait(10), "o segundo processo não iniciou")
            # A segunda leitura precisa aguardar a primeira gravação, não só o replace.
            segunda_leitura_bloqueada = not lidos[1].wait(0.3)
            continuar.set()
            for processo in processos:
                processo.join(10)
                self.assertEqual(processo.exitcode, 0)
            self.assertTrue(segunda_leitura_bloqueada, "houve leitura de registro ainda não gravado")
            self.assertEqual(set(self.registros()), {str(caminho) for caminho in caminhos})
        finally:
            continuar.set()
            for processo in processos:
                if processo.is_alive():
                    processo.terminate()
                    processo.join(5)

    def test_remocao_preserva_registro_incluido_depois_da_leitura_do_lote(self):
        self.instalar()
        kit.shutil.rmtree(self.projeto)
        outro = self.raiz / "outro"
        outro.mkdir()
        carregar = kit.carregar_projetos
        primeira_leitura = True

        def carregar_com_instalacao_concorrente():
            nonlocal primeira_leitura
            projetos = carregar()
            if primeira_leitura:
                primeira_leitura = False
                kit.registrar_projeto(outro, ["universal"], ["verificar"], True)
            return projetos

        with unittest.mock.patch.object(kit, "carregar_projetos", side_effect=carregar_com_instalacao_concorrente):
            codigo, saida, erro = rodar("update")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("removida do registro", saida)
        self.assertEqual(set(self.registros()), {str(outro)})
        self.assertEqual(self.registros()[str(outro)]["skills"], ["verificar"])

    def test_simulacao_e_instalacao_global_nao_registram(self):
        self.instalar(None, "--dry-run")
        self.assertFalse(self.registro.exists())
        config = {"universal": {"skills_global": str(self.raiz / "globais")}}
        with unittest.mock.patch.object(kit, "carregar_agentes", return_value=config):
            codigo, _, erro = rodar("install", "--global", "--agents", "universal")
        self.assertEqual(codigo, 0, erro)
        self.assertFalse(self.registro.exists())
        self.assertTrue((self.raiz / "globais/verificar/SKILL.md").is_file())

    def test_status_limpo_uma_linha_por_projeto_e_filtro(self):
        self.instalar()
        outro = self.raiz / "outro"
        outro.mkdir()
        self.instalar(outro)
        antes = self.snapshot()
        codigo, saida, erro = rodar("status")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(len(saida.splitlines()), 2)
        self.assertEqual(saida.count("em dia"), 2)
        _, saida, _ = rodar("status", str(outro), "--details")
        self.assertEqual(len(saida.splitlines()), 1)
        self.assertNotIn(str(self.projeto), saida)
        self.assertEqual(self.snapshot(), antes)

    def test_status_detecta_versao_copias_yaml_e_instrucoes(self):
        self.instalar()
        (self.projeto / ".kit-ia/VERSAO").write_text("0.1.2\n", encoding="utf-8")
        for relativo in (".kit-ia/processo/00-nucleo.md", ".claude/skills/verificar/SKILL.md"):
            (self.projeto / relativo).write_text("editada à mão", encoding="utf-8")
        yaml = self.projeto / ".kit-ia/projeto.yaml"
        yaml.write_text(yaml.read_text(encoding="utf-8").replace("  principal: main\n", "")
                        .replace("limpeza:\n  modo: perguntar", ""), encoding="utf-8")
        (self.projeto / "AGENTS.md").write_text("meu projeto", encoding="utf-8")
        (self.projeto / "CLAUDE.md").write_text("minhas instruções", encoding="utf-8")
        codigo, saida, erro = rodar("status", "--details")
        self.assertEqual(codigo, 0, erro)
        for trecho in ("instalada 0.1.2", f"atual {kit.VERSAO}", "cópia desatualizada: .kit-ia/processo",
                       "cópia desatualizada: .claude/skills/verificar", "projeto.yaml: branches.principal",
                       "projeto.yaml: limpeza", "AGENTS.md não aponta", "CLAUDE.md não importa"):
            self.assertIn(trecho, saida)
        _, curta, _ = rodar("status")
        self.assertEqual(len(curta.splitlines()), 1)

    def test_status_detecta_copias_gerenciadas_de_selecoes_anteriores(self):
        for selecao in ("skills", "agentes"):
            with self.subTest(selecao=selecao):
                projeto = self.projeto / selecao
                projeto.mkdir()
                self.instalar(projeto)
                opcoes = (["--agents", "claude,universal", "--skills", "verificar"]
                          if selecao == "skills" else ["--agents", "universal"])
                codigo, _, erro = rodar("install", str(projeto), *opcoes)
                self.assertEqual(codigo, 0, erro)
                codigo, saida, erro = rodar("status", str(projeto), "--details")
                self.assertEqual(codigo, 0, erro)
                self.assertIn("em dia", saida)
                copia = projeto / ".claude/skills/planejar/SKILL.md"
                copia.write_text("editada depois de reduzir a seleção", encoding="utf-8")
                # Uma skill própria fora da seleção continua pertencendo ao usuário.
                propria = projeto / ".claude/skills/minha-skill"
                propria.mkdir()
                (propria / "SKILL.md").write_text("própria", encoding="utf-8")
                antes = self.snapshot()
                codigo, saida, erro = rodar("status", str(projeto), "--details")
                self.assertEqual(codigo, 0, erro)
                self.assertIn("1 pendência(s)", saida)
                self.assertEqual(saida.count("cópia desatualizada: .claude/skills/planejar"), 1)
                self.assertNotIn("em dia", saida)
                self.assertNotIn("minha-skill", saida)
                self.assertEqual(self.snapshot(), antes)

    def test_status_yaml_invalido_vira_pendencia_sem_traceback(self):
        self.instalar()
        (self.projeto / ".kit-ia/projeto.yaml").write_text("nome: antes: depois", encoding="utf-8")
        codigo, saida, erro = rodar("status", "--details")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("linha 1:", saida)
        self.assertNotIn("Traceback", erro)

    def test_status_sem_registro_inspeciona_projeto_sem_escrever(self):
        self.instalar()
        self.registro.unlink()
        antes = self.snapshot()
        codigo, saida, erro = rodar("status", str(self.projeto))
        self.assertEqual(codigo, 0, erro)
        self.assertIn("em dia", saida)
        self.assertEqual(self.snapshot(), antes)

    def test_atualizar_simular_nao_escreve_e_real_restaura_copias(self):
        self.instalar()
        copia = self.projeto / ".claude/skills/verificar/SKILL.md"
        copia.write_text("edição manual", encoding="utf-8")
        (self.projeto / ".kit-ia/VERSAO").write_text("0.1.2", encoding="utf-8")
        antes = self.snapshot()
        codigo, saida, erro = rodar("update", "--dry-run")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("Resumo da atualização [simulação]", saida)
        self.assertEqual(self.snapshot(), antes)
        codigo, saida, erro = rodar("update")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("2 mudança(s), 0 aviso(s)", saida)
        self.assertEqual(copia.read_bytes(), (kit.PASTA_SKILLS / "verificar/SKILL.md").read_bytes())
        _, saida, _ = rodar("status", "--details")
        self.assertIn("em dia", saida)
        self.assertFalse((self.projeto / ".cursor").exists())

    def test_atualizar_preserva_yaml_agents_claude_e_pastas_do_usuario(self):
        self.instalar()
        proprios = {"AGENTS.md": "regras locais", "CLAUDE.md": "instruções locais",
                    ".kit-ia/projeto.yaml": "nome: próprio\n",
                    ".claude/skills/verificar/SKILL.md": "skill própria"}
        (self.projeto / ".claude/skills/verificar" / kit.MARCADOR).unlink()
        for relativo, texto in proprios.items():
            (self.projeto / relativo).write_text(texto, encoding="utf-8")
        codigo, saida, erro = rodar("update")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("3 aviso(s)", saida)
        for relativo, texto in proprios.items():
            self.assertEqual((self.projeto / relativo).read_text(encoding="utf-8"), texto)
        _, saida, _ = rodar("status", "--details")
        self.assertIn("chave ausente no projeto.yaml: branches", saida)
        self.assertIn("pasta do usuário, mantida: .claude/skills/verificar", saida)

    def test_pasta_inexistente_avisa_simulacao_preserva_e_real_remove(self):
        self.instalar()
        kit.shutil.rmtree(self.projeto)
        antes = self.snapshot()
        _, saida, _ = rodar("status")
        self.assertIn("pasta inexistente", saida)
        codigo, saida, erro = rodar("update", "--dry-run")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("seria removida do registro", saida)
        self.assertEqual(self.snapshot(), antes)
        codigo, saida, erro = rodar("update")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("removida do registro", saida)
        self.assertEqual(self.registros(), {})

    def test_atualizar_projeto_unico_nao_toca_outros_e_preserva_registro(self):
        self.instalar()
        outro = self.raiz / "outro"
        outro.mkdir()
        self.instalar(outro)
        copia = outro / ".claude/skills/verificar/SKILL.md"
        copia.write_text("edição em outro projeto", encoding="utf-8")
        codigo, _, erro = rodar("update", str(self.projeto))
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(copia.read_text(encoding="utf-8"), "edição em outro projeto")
        kit.shutil.rmtree(outro)
        codigo, _, erro = rodar("update")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(list(self.registros()), [str(self.projeto.resolve())])
        self.assertEqual(self.registros()[str(self.projeto.resolve())]["versao"], kit.VERSAO)

    def test_atualizar_nao_registrado_recusa_sem_escrever(self):
        antes = self.snapshot()
        codigo, _, erro = rodar("update", str(self.projeto))
        self.assertEqual(codigo, 1)
        self.assertIn("não registrado", erro)
        self.assertEqual(self.snapshot(), antes)

    def test_atualizar_preserva_filtro_de_skills_e_sem_mcp(self):
        self.instalar(None, "--skills", "verificar", "--no-mcp")
        codigo, _, erro = rodar("update")
        self.assertEqual(codigo, 0, erro)
        self.assertFalse((self.projeto / ".claude/skills/planejar").exists())
        self.assertFalse((self.projeto / ".mcp.json").exists())
        _, saida, _ = rodar("status")
        self.assertIn("em dia", saida)

    def test_atualizar_continua_depois_de_erro_em_um_projeto(self):
        self.instalar()
        outro = self.raiz / "z-outro"
        outro.mkdir()
        self.instalar(outro)
        (self.projeto / ".mcp.json").write_text("{", encoding="utf-8")
        copia = outro / ".claude/skills/verificar/SKILL.md"
        copia.write_text("editada", encoding="utf-8")
        codigo, saida, _ = rodar("update")
        self.assertEqual(codigo, 1)
        self.assertIn("não é um JSON válido", saida)
        self.assertIn("Resumo da atualização", saida)
        self.assertEqual(copia.read_bytes(), (kit.PASTA_SKILLS / "verificar/SKILL.md").read_bytes())

    def test_atualizar_nao_executa_mcp_global(self):
        codigo, _, erro = rodar("install", str(self.projeto), "--agents", "codex")
        self.assertEqual(codigo, 0, erro)
        with unittest.mock.patch.object(kit.subprocess, "run") as executar, \
                unittest.mock.patch("builtins.input") as perguntar:
            codigo, _, erro = rodar("update")
        self.assertEqual(codigo, 0, erro)
        executar.assert_not_called()
        perguntar.assert_not_called()

    def test_status_confere_claude_existente_mesmo_sem_agente_claude(self):
        codigo, _, erro = rodar("install", str(self.projeto), "--agents", "universal")
        self.assertEqual(codigo, 0, erro)
        (self.projeto / "CLAUDE.md").write_text("instruções próprias", encoding="utf-8")
        codigo, saida, erro = rodar("status", "--details")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("CLAUDE.md não importa", saida)

    def test_erro_de_gravacao_do_registro_vira_erro_kit(self):
        with unittest.mock.patch.object(Path, "replace", side_effect=PermissionError("acesso negado")):
            codigo, _, erro = rodar("install", str(self.projeto), "--agents", "universal")
        self.assertEqual(codigo, 1)
        self.assertIn("não consegui gravar", erro)
        self.assertNotIn("Traceback", erro)

    def test_registro_invalido_produz_erro_claro_sem_traceback(self):
        self.registro.parent.mkdir()
        for conteudo in ("{", "[]", '{"relativo": {}}'):
            with self.subTest(conteudo=conteudo):
                self.registro.write_text(conteudo, encoding="utf-8")
                for comando in ("status", "update"):
                    codigo, _, erro = rodar(comando)
                    self.assertEqual(codigo, 1)
                    self.assertIn("erro:", erro)
                    self.assertNotIn("Traceback", erro)

    def test_sem_registrados_informa_em_ambos_comandos(self):
        for comando in ("status", "update"):
            codigo, saida, erro = rodar(comando)
            self.assertEqual(codigo, 0, erro)
            self.assertIn("Nenhum projeto registrado", saida)
        self.assertFalse(self.registro.exists())


class DesinstalarTest(unittest.TestCase):
    def setUp(self):
        temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(temporaria.cleanup)
        self.raiz = Path(temporaria.name)
        self.projeto = self.raiz / "projeto com espaços"
        self.projeto.mkdir()
        ambiente = unittest.mock.patch.dict(os.environ, {"KIT_IA_HOME": str(self.raiz / "perfil")})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        executar = unittest.mock.patch.object(kit.subprocess, "run")
        self.executar = executar.start()
        self.executar.return_value.returncode = 0
        self.addCleanup(executar.stop)
        perguntar = unittest.mock.patch("builtins.input", return_value="n")
        self.perguntar = perguntar.start()
        self.addCleanup(perguntar.stop)

    def instalar(self, *opcoes):
        codigo, _, erro = rodar("install", str(self.projeto), *opcoes)
        self.assertEqual(codigo, 0, erro)

    def desinstalar(self, *opcoes):
        codigo, saida, erro = rodar("uninstall", str(self.projeto), *opcoes)
        self.assertEqual(codigo, 0, erro)
        return saida

    def snapshot(self):
        return {p.relative_to(self.raiz).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                if p.is_file() else None for p in self.raiz.rglob("*")}

    def escrever(self, relativo, texto):
        caminho = self.projeto / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8")
        return caminho

    def test_instalar_e_desinstalar_restaura_arvore_vazia_e_tira_registro(self):
        antes = list(self.projeto.rglob("*"))
        self.instalar()
        self.assertIn(str(self.projeto), kit.carregar_projetos())
        saida = self.desinstalar("--yes")
        self.assertEqual(list(self.projeto.rglob("*")), antes)
        self.assertNotIn(str(self.projeto), kit.carregar_projetos())
        self.assertIn("codex mcp remove context7", saida)
        self.assertIn("agy mcp remove context7", saida)
        self.executar.assert_not_called()
        self.perguntar.assert_not_called()

    def test_preserva_instrucoes_configuracao_skills_e_servidores_do_usuario(self):
        agents = self.escrever("AGENTS.md", "# Meu projeto\n## Como trabalhar\nRegras minhas\n")
        claude = self.escrever("CLAUDE.md", "Minhas instruções\n")
        propria = self.escrever(".agents/skills/propria/SKILL.md", "Minha skill\n")
        self.escrever(".mcp.json", json.dumps({"mcpServers": {"meu": {"url": "https://meu"}}}))
        self.escrever(".gemini/settings.json", json.dumps({"opcao": {"valor": 7}}))
        self.instalar()
        yaml = self.escrever(".kit-ia/projeto.yaml", "nome: minhas regras\n")
        preservados = {p: p.read_bytes() for p in (agents, claude, propria, yaml)}
        saida = self.desinstalar("--yes")
        for caminho, conteudo in preservados.items():
            self.assertEqual(caminho.read_bytes(), conteudo)
        self.assertEqual(kit.ler_json(self.projeto / ".mcp.json"), {"mcpServers": {"meu": {"url": "https://meu"}}})
        self.assertEqual(kit.ler_json(self.projeto / ".gemini/settings.json"), {"opcao": {"valor": 7}})
        self.assertIn("Como trabalhar", saida)
        self.assertIn("@AGENTS.md", saida)

    def test_simulacao_e_cancelamento_preservam_bytes_datas_e_registro(self):
        self.instalar()
        antes = self.snapshot()
        self.desinstalar("--dry-run", "--mcp-global", "--yes")
        self.assertEqual(self.snapshot(), antes)
        self.perguntar.assert_not_called()
        self.desinstalar("--mcp-global")
        self.assertEqual(self.snapshot(), antes)
        self.perguntar.assert_called_once_with("Remover? [s/N] ")
        self.executar.assert_not_called()

    def test_confirmacao_local_s_nao_executa_mcp_sem_opcao(self):
        self.instalar()
        self.perguntar.return_value = "s"
        self.desinstalar()
        self.assertEqual(list(self.projeto.iterdir()), [])
        self.perguntar.assert_called_once_with("Remover? [s/N] ")
        self.executar.assert_not_called()

    def test_edicao_durante_confirmacao_e_preservada(self):
        self.instalar()
        caminho = self.projeto / "AGENTS.md"

        def editar_e_confirmar(_):
            caminho.write_text("Minhas novas regras", encoding="utf-8")
            (self.projeto / ".agents/skills/verificar" / kit.MARCADOR).unlink()
            return "s"

        self.perguntar.side_effect = editar_e_confirmar
        saida = self.desinstalar()
        self.assertEqual(caminho.read_text(encoding="utf-8"), "Minhas novas regras")
        self.assertTrue((self.projeto / ".agents/skills/verificar/SKILL.md").is_file())
        self.assertIn("depois da prévia", saida)

    def test_eof_cancela_remocao(self):
        self.instalar()
        antes = self.snapshot()
        self.perguntar.side_effect = EOFError
        self.desinstalar()
        self.assertEqual(self.snapshot(), antes)

    def test_mcp_global_exige_opcao_e_confirmacao_propria_mesmo_com_yes(self):
        for resposta in ("n", "s"):
            with self.subTest(resposta=resposta):
                self.instalar()
                self.perguntar.reset_mock()
                self.executar.reset_mock()
                self.perguntar.return_value = resposta
                with unittest.mock.patch.object(kit, "localizar_executavel", side_effect=lambda nome, _: nome):
                    self.desinstalar("--yes", "--mcp-global")
                self.perguntar.assert_called_once_with("Executar estes comandos? [s/N] ")
                if resposta == "s":
                    self.assertEqual([chamada.args[0] for chamada in self.executar.call_args_list], [
                        ["codex", "mcp", "remove", "context7"], ["agy", "mcp", "remove", "context7"]])
                else:
                    self.executar.assert_not_called()

    def test_confirmacao_mcp_separada_apos_confirmacao_local(self):
        self.instalar()
        self.perguntar.side_effect = ["s", "n"]
        self.desinstalar("--mcp-global")
        self.assertEqual(list(self.projeto.iterdir()), [])
        self.assertEqual(self.perguntar.call_count, 2)
        self.executar.assert_not_called()

    def test_pastas_sem_marcador_e_arquivos_alterados_ficam(self):
        self.instalar()
        pasta = self.projeto / ".kit-ia/processo"
        (pasta / kit.MARCADOR).unlink()
        skill = self.projeto / ".claude/skills/verificar"
        (skill / kit.MARCADOR).unlink()
        versao = self.escrever(".kit-ia/VERSAO", "minha versão")
        self.desinstalar("--yes")
        self.assertTrue((pasta / "00-nucleo.md").is_file())
        self.assertTrue((skill / "SKILL.md").is_file())
        self.assertEqual(versao.read_text(encoding="utf-8"), "minha versão")

    def test_selecao_de_agentes_mantem_skills_de_outros_agentes(self):
        self.instalar()
        self.desinstalar("--agents", "universal", "--yes")
        self.assertFalse((self.projeto / ".agents").exists())
        self.assertTrue((self.projeto / ".claude/skills/verificar/SKILL.md").is_file())
        self.assertTrue((self.projeto / "CLAUDE.md").is_file())
        self.assertTrue((self.projeto / ".mcp.json").is_file())

    def test_json_invalido_ou_nao_objeto_e_preservado_com_aviso(self):
        self.instalar()
        for texto in ("{invalido", "[]", "null", "42"):
            with self.subTest(texto=texto):
                caminho = self.escrever(".mcp.json", texto)
                saida = self.desinstalar("--yes")
                self.assertEqual(caminho.read_text(encoding="utf-8"), texto)
                self.assertIn("mantido", saida)

    def test_mcp_sem_entradas_do_kit_nao_e_regravado(self):
        for texto in ('{ "mcpServers": {} }', '{"mcpServers": {"context7": {"url": "minha"}}}',
                      '{"mcpServers": [], "context": {"fileName": "MEU.md"}}'):
            with self.subTest(texto=texto):
                caminho = self.escrever(".gemini/settings.json", texto)
                antes = caminho.stat().st_mtime_ns
                self.desinstalar("--yes")
                self.assertEqual(caminho.read_text(encoding="utf-8"), texto)
                self.assertEqual(caminho.stat().st_mtime_ns, antes)

    def test_mcp_identico_remove_e_alterado_preserva_em_todos_formatos(self):
        self.instalar()
        preservados = {}
        for cfg in kit.carregar_agentes().values():
            mcp = cfg.get("mcp", {})
            if mcp.get("formato") not in kit.CHAVE_DOS_SERVIDORES:
                continue
            caminho = self.projeto / mcp["arquivo"]
            dados = kit.ler_json(caminho)
            dados[kit.CHAVE_DOS_SERVIDORES[mcp["formato"]]]["context7"]["extra_usuario"] = 1
            if mcp["formato"] == "gemini":
                dados["context"]["fileName"].append("MEU.md")
            caminho.write_text(json.dumps(dados), encoding="utf-8")
            preservados[caminho] = caminho.read_bytes()
        self.desinstalar("--yes")
        for caminho, texto in preservados.items():
            self.assertEqual(caminho.read_bytes(), texto)

    def test_servidor_stdio_convertido_tambem_e_removido(self):
        servidores = {"local": {"tipo": "stdio", "comando": "npx", "args": ["servidor"],
                                "env": {"CHAVE": "${CHAVE}"}},
                      "remoto": {"tipo": "http", "url": "https://servidor", "cabecalhos": {"X": "${CHAVE}"}}}
        with unittest.mock.patch.object(kit, "carregar_servidores", return_value=servidores):
            self.instalar()
            self.desinstalar("--yes")
        self.assertEqual(list(self.projeto.iterdir()), [])

    def test_global_remove_apenas_skills_marcadas_no_perfil_isolado(self):
        perfil = self.raiz / "global"
        agentes = {"teste": {"skills_global": str(perfil / ".agents/skills")}}
        propria = perfil / ".agents/skills/propria/SKILL.md"
        propria.parent.mkdir(parents=True)
        propria.write_text("própria", encoding="utf-8")
        with unittest.mock.patch.object(kit, "carregar_agentes", return_value=agentes):
            self.assertEqual(rodar("install", "--global")[0], 0)
            antes = self.snapshot()
            self.assertEqual(rodar("uninstall", "--global", "--dry-run")[0], 0)
            self.assertEqual(self.snapshot(), antes)
            self.assertEqual(rodar("uninstall", "--global", "--yes")[0], 0)
        self.assertEqual(list(propria.parent.parent.iterdir()), [propria.parent])
        self.assertEqual(propria.read_text(encoding="utf-8"), "própria")
        self.assertFalse(kit.arquivo_projetos().exists())
        self.executar.assert_not_called()

    def test_caminho_com_desvio_nao_pode_ser_removido(self):
        caminho = self.projeto / ".agents/skills"
        with unittest.mock.patch.object(Path, "is_symlink", side_effect=lambda: True):
            self.assertFalse(kit.caminho_sem_desvios(caminho, self.projeto))
        self.assertFalse(kit.caminho_sem_desvios(self.raiz / "fora", self.projeto))
        self.assertFalse(kit.caminho_sem_desvios(self.projeto, self.projeto))

    def test_reparse_point_preserva_skills_mesmo_sem_isjunction(self):
        marcador = self.escrever(".agents/skills/externa/.kit-ia", "kit")
        skill = self.escrever(".agents/skills/externa/SKILL.md", "conteúdo externo")
        antes = self.snapshot()
        lstat = Path.lstat
        for desvio in (self.projeto / ".agents", skill.parent):
            with self.subTest(desvio=desvio):
                def atributos(caminho):
                    if caminho == desvio:
                        return unittest.mock.Mock(st_file_attributes=1024, st_mode=lstat(caminho).st_mode)
                    return lstat(caminho)

                sem_api = (unittest.mock.patch.object(os.path, "isjunction")
                           if hasattr(os.path, "isjunction") else contextlib.nullcontext())
                with sem_api, unittest.mock.patch.object(Path, "lstat", atributos):
                    if hasattr(os.path, "isjunction"):
                        del os.path.isjunction
                    saida = self.desinstalar("--agents", "universal", "--yes")
                self.assertEqual(self.snapshot(), antes)
                self.assertEqual(skill.read_text(encoding="utf-8"), "conteúdo externo")
                self.assertTrue(marcador.is_file())
                self.assertIn("caminho com link, junção ou fora do destino; mantido", saida)

    def test_destino_fisico_fora_do_projeto_nao_autoriza_remocao(self):
        caminho = self.projeto / ".agents/skills"
        caminho.mkdir(parents=True)
        resolver = Path.resolve

        def destino_fisico(parte, *args, **kwargs):
            if parte == caminho:
                return self.raiz / "externa/skills"
            return resolver(parte, *args, **kwargs)

        with unittest.mock.patch.object(Path, "resolve", destino_fisico):
            self.assertFalse(kit.caminho_sem_desvios(caminho, self.projeto))

    def test_sem_comprovar_caminho_fisico_nao_autoriza_remocao(self):
        caminho = self.projeto / ".agents/skills"
        caminho.mkdir(parents=True)
        for metodo in ("lstat", "resolve"):
            with self.subTest(metodo=metodo), \
                 unittest.mock.patch.object(Path, metodo, side_effect=PermissionError("sem acesso")):
                self.assertFalse(kit.caminho_sem_desvios(caminho, self.projeto))

    def test_argumentos_invalidos_tem_erro_claro(self):
        for argumentos in ((), (str(self.projeto / "ausente"),), (str(self.projeto), "--global"),
                           (str(self.projeto), "--agents", "ausente")):
            with self.subTest(argumentos=argumentos):
                codigo, _, erro = rodar("uninstall", *argumentos)
                self.assertEqual(codigo, 1)
                self.assertIn("erro:", erro)

    def test_erro_de_acesso_vira_erro_kit_sem_traceback(self):
        with unittest.mock.patch.object(kit, "carregar_projetos", side_effect=PermissionError("sem acesso")):
            codigo, _, erro = rodar("uninstall", str(self.projeto), "--yes")
        self.assertEqual(codigo, 1)
        self.assertIn("sem acesso", erro)
        self.assertNotIn("Traceback", erro)


class InterfaceInglesTest(unittest.TestCase):
    def test_readme_informa_a_versao_atual_da_cli(self):
        readme = (kit.RAIZ / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"Versão atual: **{kit.VERSAO}**", readme)

    def test_comandos_antigos_nao_tem_alias(self):
        for comando in ("listar", "validar", "instalar", "nova-skill", "executar", "custo", "atualizar"):
            with self.subTest(comando=comando), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as erro:
                    kit.montar_parser().parse_args([comando])
                self.assertEqual(erro.exception.code, 2)

    def test_opcoes_antigas_sao_rejeitadas(self):
        casos = {"install": ["simular", "forcar", "agentes", "sem-mcp"],
                 "run": ["entrada", "protocolo", "modelo"], "new-skill": ["descricao"],
                 "cost": ["desde", "ate", "por", "lote", "projeto", "verificar-orcamento"],
                 "status": ["detalhes"], "": ["versao"]}
        for comando, opcoes in casos.items():
            for opcao in opcoes:
                argumentos = [comando] if comando else []
                if comando in ("run", "new-skill"):
                    argumentos.append("verificar")
                with self.subTest(opcao=opcao), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as erro:
                        kit.montar_parser().parse_args([*argumentos, "--" + opcao])
                    self.assertEqual(erro.exception.code, 2)

    def test_custo_agrupa_em_ingles_sem_traduzir_chaves_dos_dados(self):
        inicio = kit.custo.data("2026-11-16T10:00:00Z")
        registro = kit.custo.registro("codex", "modelo", "executor", str(Path.cwd()), "BL-LU-5",
                                     inicio, inicio, {"entrada": 3, "saida": 2})
        with unittest.mock.patch.object(kit.custo, "coletar", return_value=([registro], [])):
            for opcao, chave, esperado in (("task", "task", "BL-LU-5"), ("model", "modelo", "modelo"),
                                          ("agent", "agente", "codex"), ("role", "papel", "executor"),
                                          ("day", "dia", "2026-11-16")):
                with self.subTest(opcao=opcao):
                    codigo, saida, erro = rodar("cost", "--by", opcao, "--json")
                    self.assertEqual(codigo, 0, erro)
                    grupo = json.loads(saida)["grupos"][0]
                    self.assertEqual(grupo[chave], esperado)
                    self.assertEqual(grupo["tokens"], 5)
            for opcao in ("modelo", "agente", "papel", "dia"):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    kit.montar_parser().parse_args(["cost", "--by", opcao])

    def test_custo_filtros_novos_preservam_intervalo_e_isolam_projeto(self):
        base = Path.cwd()
        inicio = kit.custo.data("2026-11-16T23:00:00Z")
        fim = kit.custo.data("2026-11-17T01:00:00Z")
        registros = [kit.custo.registro("codex", "modelo", "executor", str(pasta), "BL-LU-5",
                                      inicio, fim, {"entrada": tokens, "saida": 0})
                     for pasta, tokens in ((base, 5), (base.parent / "outro", 100))]
        with unittest.mock.patch.object(kit.custo, "coletar", return_value=(registros, [])), \
             unittest.mock.patch.object(kit.custo, "raizes_projeto", return_value=[base]):
            codigo, saida, erro = rodar("cost", "--project", str(base), "--since", "2026-11-17",
                                      "--until", "2026-11-17", "--json")
            self.assertEqual(codigo, 0, erro)
            self.assertEqual(json.loads(saida)["grupos"][0]["tokens"], 5)
            self.assertEqual(json.loads(rodar("cost", "--until", "2026-11-15", "--json")[1])["grupos"], [])
        for argumentos in (("--until", "ontem"), ("--since", "2026-11-18", "--until", "2026-11-17")):
            self.assertEqual(rodar("cost", *argumentos)[0], 1)

    def test_agrupamento_dia_normaliza_fuso_e_preserva_data_desconhecida(self):
        inicio = kit.custo.data("2026-11-17T01:00:00+03:00")
        registros = [kit.custo.registro("kit", "modelo", "executar", "", "", instante, instante,
                                      {"entrada": 3, "saida": 2}) for instante in (inicio, None)]
        with unittest.mock.patch.object(kit.custo, "coletar", return_value=(registros, [])):
            codigo, saida, erro = rodar("cost", "--by", "day", "--json")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual({grupo["dia"] for grupo in json.loads(saida)["grupos"]}, {"2026-11-16", "(sem data)"})

    def test_list_e_version_novos(self):
        self.assertEqual(rodar("list")[0], 0)
        with contextlib.redirect_stdout(io.StringIO()) as saida, self.assertRaises(SystemExit) as erro:
            kit.montar_parser().parse_args(["--version"])
        self.assertEqual(erro.exception.code, 0)
        self.assertIn("0.3.0", saida.getvalue())


class NovaSkillTest(unittest.TestCase):
    def test_cria_skill_valida(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = kit.PASTA_SKILLS
            kit.PASTA_SKILLS = Path(tmp)
            try:
                codigo, _, erro = rodar("new-skill", "gerar-changelog", "--description", "Gera. Use quando X.")
                self.assertEqual(codigo, 0, erro)
                self.assertEqual(kit.problemas_da_skill(Path(tmp) / "gerar-changelog"), [])
                codigo, _, erro = rodar("new-skill", "Nome Invalido")
                self.assertEqual(codigo, 1)
            finally:
                kit.PASTA_SKILLS = original


class ProvedorFalso(BaseHTTPRequestHandler):
    """Finge ser um provedor de modelo. Guarda a última requisição para o teste conferir."""
    ultima: dict = {}

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ProvedorFalso.ultima = {"caminho": self.path, "corpo": corpo, "cabecalhos": {k.lower(): v for k, v in self.headers.items()}}
        if corpo.get("model") == "nao-autorizado":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "chave invalida"}')
            return
        if corpo.get("model") == "recusa":
            resposta = {"stop_reason": "refusal", "stop_details": {"category": "teste"}, "content": []}
        elif self.path.endswith("/messages"):
            resposta = {"usage": {"input_tokens": 20, "output_tokens": 8}, "stop_reason": "end_turn", "content": [
                {"type": "thinking", "thinking": ""}, {"type": "text", "text": "resposta anthropic"}]}
        else:
            resposta = {"usage": {"prompt_tokens": 30, "completion_tokens": 10, "cost": .001},
                        "choices": [{"message": {"content": "resposta openai"}}]}
        if corpo.get("model") == "telemetria-invalida":
            resposta["usage"]["prompt_tokens_details"] = [1]
        if corpo.get("model") in ("cache-leitura-parcial", "cache-escrita-parcial"):
            campo = ("cache_read_input_tokens" if corpo["model"] == "cache-leitura-parcial"
                     else "cache_creation_input_tokens")
            resposta["usage"] = {"input_tokens": None, "output_tokens": 1, campo: 500000}
        if corpo.get("model") == "openai-cache-parcial":
            resposta["usage"] = {"prompt_tokens": None, "completion_tokens": 1,
                                 "prompt_tokens_details": {"cached_tokens": 500000}}
        dados = json.dumps(resposta).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args):
        pass


class ExecutarTest(unittest.TestCase):
    def test_openai_cache_com_entrada_nula_preserva_estouro_reportado(self):
        raiz = Path(self.temporaria.name)
        (raiz / "projeto.yaml").write_text("orcamento: {por_task: {tokens: 400000, minutos: 30}}", encoding="utf-8")
        ambiente = {"KIT_IA_CLAUDE_DIR": str(raiz / "claude"), "KIT_IA_CODEX_DIR": str(raiz / "codex"),
                    "KIT_IA_ANTIGRAVITY_DIR": str(raiz / "antigravity")}
        with unittest.mock.patch.dict(os.environ, ambiente), unittest.mock.patch("kit.custo.Path.cwd", return_value=raiz):
            codigo, _, erro = rodar("run", "revisar", "--input", "pedido",
                "--url", self.url, "--model", "openai-cache-parcial", "--protocol", "openai", "--task", "BL-LU-3")
            self.assertEqual(codigo, 0, erro)
            uso = json.loads((raiz / "uso.jsonl").read_text(encoding="utf-8"))
            self.assertEqual((uso["entrada"], uso["saida"]), (500000, 1))
            self.assertTrue(uso["parcial"])
            self.assertFalse(uso["custo_confiavel"])
            codigo, saida, erro = rodar("cost", "--check-budget", str(raiz / "projeto.yaml"), "--json")
        self.assertEqual(codigo, 1, erro)
        grupo = json.loads(saida)["grupos"][0]
        self.assertEqual(grupo["limite_superior_tokens"], 500001)
        self.assertTrue(grupo["medicao_incompleta"])
        self.assertIsNone(grupo["custo_usd"])

    def setUp(self):
        self.temporaria = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporaria.cleanup)
        self.ambiente = unittest.mock.patch.dict(os.environ, {"KIT_IA_HOME": self.temporaria.name})
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)

    @classmethod
    def setUpClass(cls):
        cls.servidor = HTTPServer(("127.0.0.1", 0), ProvedorFalso)
        cls.url = f"http://127.0.0.1:{cls.servidor.server_port}/v1"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def test_protocolo_openai(self):
        codigo, saida, erro = rodar("run", "revisar", "--input", "diff aqui",
                                    "--url", self.url, "--model", "falso", "--protocol", "openai")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(saida.strip(), "resposta openai")
        req = ProvedorFalso.ultima
        self.assertEqual(req["caminho"], "/v1/chat/completions")
        mensagens = req["corpo"]["messages"]
        self.assertIn("# Revisar um diff", mensagens[0]["content"])
        self.assertEqual(mensagens[1], {"role": "user", "content": "diff aqui"})

    def test_protocolo_anthropic(self):
        with unittest.mock.patch.dict("os.environ", {"KIT_IA_CHAVE": "chave-teste"}):
            codigo, saida, erro = rodar("run", "planejar", "--input", "pedido",
                                        "--url", self.url, "--model", "m", "--protocol", "anthropic")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(saida.strip(), "resposta anthropic")
        req = ProvedorFalso.ultima
        self.assertEqual(req["caminho"], "/v1/messages")
        self.assertEqual(req["cabecalhos"]["x-api-key"], "chave-teste")
        self.assertIn("# Planejar uma mudança", req["corpo"]["system"])

    def test_registra_uso_dos_protocolos_sem_chave_ou_conversa(self):
        for protocolo, entrada, saida, custo in (("openai", 30, 10, .001), ("anthropic", 20, 8, None)):
            with self.subTest(protocolo=protocolo), unittest.mock.patch.dict(os.environ, {"KIT_IA_CHAVE": "segredo-nao-gravar"}):
                codigo, _, erro = rodar("run", "revisar", "--input", "conteudo-nao-gravar",
                    "--url", self.url, "--model", "falso", "--protocol", protocolo, "--task", "BL-LU-3")
                self.assertEqual(codigo, 0, erro)
                texto = (Path(self.temporaria.name) / "uso.jsonl").read_text(encoding="utf-8")
                registro = json.loads(texto.splitlines()[-1])
                self.assertEqual((registro["entrada"], registro["saida"], registro["custo_usd"]), (entrada, saida, custo))
                self.assertEqual(registro["task"], "BL-LU-3")
                self.assertGreaterEqual(registro["duracao_segundos"], 0)
                self.assertNotIn("segredo-nao-gravar", texto)
                self.assertNotIn("conteudo-nao-gravar", texto)
                self.assertNotIn("resposta openai", texto)

    def test_anthropic_cache_com_entrada_desconhecida_preserva_estouro_no_registro(self):
        raiz = Path(self.temporaria.name)
        projeto = raiz / ".kit-ia/projeto.yaml"
        projeto.parent.mkdir()
        projeto.write_text("orcamento:\n  por_task: {tokens: 400000, minutos: 30}", encoding="utf-8")
        ambiente = {"KIT_IA_CHAVE": "chave-teste", "KIT_IA_CLAUDE_DIR": str(raiz / "claude"),
                    "KIT_IA_CODEX_DIR": str(raiz / "codex"),
                    "KIT_IA_ANTIGRAVITY_DIR": str(raiz / "antigravity")}
        for modelo in ("cache-leitura-parcial", "cache-escrita-parcial"):
            with self.subTest(modelo=modelo), unittest.mock.patch.dict(os.environ, ambiente), \
                    unittest.mock.patch("kit.custo.Path.cwd", return_value=raiz):
                (raiz / "uso.jsonl").unlink(missing_ok=True)
                codigo, saida, erro = rodar("run", "revisar", "--input", "pedido",
                    "--url", self.url, "--model", modelo, "--protocol", "anthropic", "--task", "BL-LU-3")
                self.assertEqual(codigo, 0, erro)
                self.assertEqual(saida.strip(), "resposta anthropic")
                uso = json.loads((raiz / "uso.jsonl").read_text(encoding="utf-8"))
                self.assertEqual((uso["entrada"], uso["saida"]), (500000, 1))
                self.assertTrue(uso["parcial"])
                self.assertFalse(uso["custo_confiavel"])
                precos = raiz / "config/precos.json"
                precos.parent.mkdir(exist_ok=True)
                precos.write_text(json.dumps({"precos": {modelo: {
                    "entrada": 1, "saida": 1, "cache_leitura": 1, "cache_escrita": 1}}}), encoding="utf-8")
                with unittest.mock.patch("kit.RAIZ", raiz):
                    codigo, saida, erro = rodar("cost", "--check-budget", str(raiz), "--json")
                self.assertEqual(codigo, 1, erro)
                dados = json.loads(saida)
                self.assertEqual(len(dados["grupos"]), 1)
                grupo = dados["grupos"][0]
                self.assertEqual(grupo["tokens"], 500001)
                self.assertTrue(grupo["parcial"])
                self.assertIsNone(grupo["custo_usd"])
                self.assertEqual(len(dados["estouros"]), 1)
                self.assertIn("BL-LU-3: tokens 500001.00 > 400000", dados["estouros"][0])

    def test_falha_de_registro_so_avisa(self):
        with unittest.mock.patch("kit.custo.registrar_uso", side_effect=OSError("disco indisponível")):
            codigo, saida, erro = rodar("run", "revisar", "--input", "x", "--url", self.url, "--protocol", "openai")
        self.assertEqual(codigo, 0)
        self.assertIn("resposta openai", saida)
        self.assertIn("aviso:", erro)

    def test_telemetria_malformada_preserva_resposta_valida(self):
        codigo, saida, erro = rodar("run", "revisar", "--input", "x", "--url", self.url,
                                    "--model", "telemetria-invalida", "--protocol", "openai")
        self.assertEqual(codigo, 0)
        self.assertEqual(saida.strip(), "resposta openai")
        self.assertIn("aviso: telemetria de uso inválida", erro)
        self.assertNotIn("Traceback", erro)
        self.assertFalse((Path(self.temporaria.name) / "uso.jsonl").exists())

    def test_custo_cli_sem_fontes_e_erro_de_data(self):
        with unittest.mock.patch("kit.custo.coletar", return_value=([], [])):
            codigo, saida, _ = rodar("cost", "--json")
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(saida)["grupos"], [])
            self.assertEqual(rodar("cost", "--since", "invalida")[0], 1)

    def test_provedor_fora_do_ar_vira_mensagem(self):
        codigo, _, erro = rodar("run", "revisar", "--input", "x",
                                "--url", "http://127.0.0.1:1/v1", "--protocol", "openai")
        self.assertEqual(codigo, 1)
        self.assertIn("não consegui conectar", erro)
        registro = json.loads((Path(self.temporaria.name) / "uso.jsonl").read_text(encoding="utf-8"))
        self.assertIsNone(registro["entrada"])
        self.assertGreaterEqual(registro["duracao_segundos"], 0)

    def test_skill_inexistente_e_erro(self):
        codigo, _, erro = rodar("run", "nao-existe", "--input", "x")
        self.assertEqual(codigo, 1)
        self.assertIn("não encontrada", erro)

    def test_entrada_de_arquivo_e_de_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "mudanca.diff"
            arquivo.write_text("conteúdo do arquivo", encoding="utf-8")
            rodar("run", "revisar", "--input", str(arquivo), "--url", self.url, "--protocol", "openai")
        self.assertEqual(ProvedorFalso.ultima["corpo"]["messages"][1]["content"], "conteúdo do arquivo")

        with unittest.mock.patch("sys.stdin", io.StringIO("diff via pipe")):
            codigo, _, erro = rodar("run", "revisar", "--url", self.url, "--protocol", "openai")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(ProvedorFalso.ultima["corpo"]["messages"][1]["content"], "diff via pipe")

    def test_recusa_do_modelo_vira_erro(self):
        with unittest.mock.patch.dict("os.environ", {"KIT_IA_CHAVE": "k"}):
            codigo, _, erro = rodar("run", "revisar", "--input", "x", "--url", self.url,
                                    "--protocol", "anthropic", "--model", "recusa")
        self.assertEqual(codigo, 1)
        self.assertIn("recusou", erro)

    def test_erro_http_do_provedor_vira_mensagem(self):
        codigo, _, erro = rodar("run", "revisar", "--input", "x", "--url", self.url,
                                "--protocol", "openai", "--model", "nao-autorizado")
        self.assertEqual(codigo, 1)
        self.assertIn("HTTP 401", erro)
        self.assertIn("chave invalida", erro)


class ConfigModeloTest(unittest.TestCase):
    """Ordem de prioridade: argumento > variável de ambiente > .env > padrão."""

    def config(self, env_sistema: dict, conteudo_env: str = "", **argumentos) -> dict:
        args = argparse.Namespace(protocolo=None, url=None, modelo=None)
        for chave, valor in argumentos.items():
            setattr(args, chave, valor)
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / ".env"
            arquivo.write_text(conteudo_env, encoding="utf-8")
            limpo = {k: v for k, v in os.environ.items() if not k.startswith("KIT_IA_")}
            with unittest.mock.patch.object(kit, "ARQUIVO_ENV", arquivo), \
                    unittest.mock.patch.dict("os.environ", {**limpo, **env_sistema}, clear=True):
                return kit.config_modelo(args)

    def test_padrao_e_ollama_local(self):
        cfg = self.config({})
        self.assertEqual((cfg["protocolo"], cfg["url"], cfg["modelo"]),
                         ("openai", "http://localhost:11434/v1", "qwen2.5:3b"))

    def test_env_arquivo_vence_padrao(self):
        cfg = self.config({}, "KIT_IA_MODELO=do-arquivo\nKIT_IA_URL=http://arquivo/v1/\n")
        self.assertEqual(cfg["modelo"], "do-arquivo")
        self.assertEqual(cfg["url"], "http://arquivo/v1")  # barra final removida

    def test_variavel_de_ambiente_vence_arquivo(self):
        cfg = self.config({"KIT_IA_MODELO": "do-sistema"}, "KIT_IA_MODELO=do-arquivo\n")
        self.assertEqual(cfg["modelo"], "do-sistema")

    def test_argumento_vence_tudo(self):
        cfg = self.config({"KIT_IA_MODELO": "do-sistema"}, "KIT_IA_MODELO=do-arquivo\n", modelo="do-argumento")
        self.assertEqual(cfg["modelo"], "do-argumento")

    def test_protocolo_invalido_e_erro(self):
        with self.assertRaises(kit.ErroKit):
            self.config({"KIT_IA_PROTOCOLO": "xpto"})


if __name__ == "__main__":
    unittest.main()
