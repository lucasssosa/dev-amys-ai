"""Testes do kit.py. Rodar com: python -m unittest discover -s tests -v"""
import argparse
import contextlib
import io
import json
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


class ProjetoYamlTest(unittest.TestCase):
    def test_orcamento_rejeita_yaml_invalido_sem_traceback(self):
        with tempfile.TemporaryDirectory() as temporaria:
            projeto = Path(temporaria) / "projeto.yaml"
            projeto.write_text("nome: antes: depois\norcamento: {por_task: {tokens: 400000, minutos: 30}}",
                               encoding="utf-8")
            with unittest.mock.patch("kit.custo.coletar", return_value=([], [])):
                codigo, _, erro = rodar("custo", "--verificar-orcamento", str(projeto))
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
        codigo, saida, _ = rodar("validar")
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
                codigo, _, erro = rodar("validar")
        self.assertEqual(codigo, 1)
        self.assertIn("precisa de 'url'", erro)

    def test_listar_e_versao(self):
        codigo, saida, _ = rodar("listar")
        self.assertEqual(codigo, 0)
        self.assertIn("verificar", saida)
        with self.assertRaises(SystemExit) as fim, contextlib.redirect_stdout(io.StringIO()) as saida:
            kit.main(["--versao"])
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
        codigo, saida, erro = rodar("instalar", str(self.projeto))
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
        rodar("instalar", str(self.projeto))
        codigo, saida, _ = rodar("instalar", str(self.projeto))
        self.assertEqual(codigo, 0)
        self.assertIn("0 mudança(s)", saida)

    def test_simular_nao_escreve(self):
        codigo, saida, _ = rodar("instalar", str(self.projeto), "--simular")
        self.assertEqual(codigo, 0)
        self.assertIn("[simulação]", saida)
        self.assertEqual(list(self.projeto.iterdir()), [])

    def test_filtra_agentes_e_skills(self):
        rodar("instalar", str(self.projeto), "--agentes", "claude", "--skills", "verificar")
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

        codigo, saida, _ = rodar("instalar", str(self.projeto), "--agentes", "claude")

        self.assertEqual(codigo, 0)
        self.assertEqual((self.projeto / "AGENTS.md").read_text(encoding="utf-8"), "meu agents")
        self.assertEqual((propria / "SKILL.md").read_text(encoding="utf-8"), "minha skill")
        servidores = self.ler_json(".mcp.json")["mcpServers"]
        self.assertEqual(servidores["tarefas"]["url"], "http://localhost:8080/mcp")
        self.assertEqual(servidores["context7"]["url"], "https://outro")
        self.assertIn("não importa o AGENTS.md", saida)
        self.assertIn("não foi instalada pelo kit", saida)

    def test_reinstalar_atualiza_skill_do_kit(self):
        rodar("instalar", str(self.projeto), "--agentes", "claude")
        copia = self.projeto / ".claude/skills/verificar/SKILL.md"
        copia.write_text("editada à mão", encoding="utf-8")
        rodar("instalar", str(self.projeto), "--agentes", "claude")
        self.assertEqual(copia.read_text(encoding="utf-8"),
                         (kit.PASTA_SKILLS / "verificar/SKILL.md").read_text(encoding="utf-8"))

    def test_preserva_projeto_yaml_e_restaura_processo(self):
        rodar("instalar", str(self.projeto), "--agentes", "claude")
        projeto_yaml = self.projeto / ".kit-ia/projeto.yaml"
        projeto_yaml.write_text("meu projeto.yaml", encoding="utf-8")
        nucleo = self.projeto / ".kit-ia/processo/00-nucleo.md"
        nucleo.write_text("editado à mão", encoding="utf-8")

        rodar("instalar", str(self.projeto), "--agentes", "claude")

        self.assertEqual(projeto_yaml.read_text(encoding="utf-8"), "meu projeto.yaml")
        self.assertEqual(nucleo.read_text(encoding="utf-8"),
                         (kit.RAIZ / "processo/00-nucleo.md").read_text(encoding="utf-8"))

    def test_avisa_agents_md_que_nao_aponta_o_processo(self):
        (self.projeto / "AGENTS.md").write_text("# Meu projeto\n", encoding="utf-8")
        _, saida, _ = rodar("instalar", str(self.projeto), "--agentes", "universal")
        self.assertIn("não aponta o processo", saida)

    def test_forcar_substitui_skill_e_servidor_do_usuario(self):
        propria = self.projeto / ".claude/skills/verificar"
        propria.mkdir(parents=True)
        (propria / "SKILL.md").write_text("minha skill", encoding="utf-8")
        (self.projeto / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "context7": {"type": "http", "url": "https://outro"}}}), encoding="utf-8")

        rodar("instalar", str(self.projeto), "--agentes", "claude", "--forcar")

        self.assertEqual((propria / "SKILL.md").read_text(encoding="utf-8"),
                         (kit.PASTA_SKILLS / "verificar/SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(self.ler_json(".mcp.json")["mcpServers"]["context7"]["url"], "https://mcp.context7.com/mcp")

    def test_preserva_toml_do_codex_existente(self):
        toml = self.projeto / ".codex/config.toml"
        toml.parent.mkdir()
        toml.write_text('model = "x"\n\n[mcp_servers.meu]\nurl = "http://localhost:9000/mcp"\n', encoding="utf-8")

        rodar("instalar", str(self.projeto), "--agentes", "codex")
        rodar("instalar", str(self.projeto), "--agentes", "codex")

        self.assertEqual(toml.read_text(encoding="utf-8"),
                         'model = "x"\n\n[mcp_servers.meu]\nurl = "http://localhost:9000/mcp"\n')

    def test_codex_e_antigravity_sozinhos_instalam_skills(self):
        for agente in ("codex", "antigravity"):
            with self.subTest(agente=agente):
                projeto = self.projeto / agente
                projeto.mkdir()
                codigo, _, erro = rodar("instalar", str(projeto), "--agentes", agente)
                self.assertEqual(codigo, 0, erro)
                self.assertTrue((projeto / ".agents/skills/verificar/SKILL.md").is_file())
                self.assertFalse((projeto / ".codex").exists())
                self.assertFalse((projeto / ".gemini").exists())

    def test_cabecalho_codex_vira_aviso_sem_comando(self):
        servidores = {"com-header": {"tipo": "http", "url": "https://x/mcp",
                                     "cabecalhos": {"X-Cliente": "kit"}},
                      "sem-header": {"tipo": "http", "url": "https://y/mcp"}}
        with unittest.mock.patch.object(kit, "carregar_servidores", return_value=servidores):
            codigo, saida, erro = rodar("instalar", str(self.projeto), "--agentes", "codex")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("configure à mão", saida)
        self.assertIn("1 aviso(s)", saida)
        self.assertNotIn("mcp add com-header", saida)
        self.assertIn("mcp add sem-header", saida)

    def test_mcp_global_exige_flag_mesmo_com_resposta_s(self):
        self.perguntar.return_value = "s"
        rodar("instalar", str(self.projeto))
        self.perguntar.assert_not_called()
        self.executar.assert_not_called()

    def test_mcp_global_confirmado_executa_argumentos_sem_shell(self):
        self.perguntar.return_value = "s"
        with unittest.mock.patch.object(kit.shutil, "which", side_effect=lambda nome: f"/bin/{nome}"):
            codigo, _, erro = rodar("instalar", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.perguntar.assert_called_once_with("Executar estes comandos? [s/N] ")
        self.assertEqual(self.executar.call_args_list, [
            unittest.mock.call(["/bin/codex", "mcp", "add", "context7", "--url", "https://mcp.context7.com/mcp"], check=False),
            unittest.mock.call(["/bin/agy", "mcp", "add", "context7", "https://mcp.context7.com/mcp"], check=False)])

    def test_mcp_global_recusado_nao_executa(self):
        for resposta in ("n", "", "sim"):
            with self.subTest(resposta=resposta):
                self.perguntar.return_value = resposta
                rodar("instalar", str(self.projeto), "--mcp-global")
                self.executar.assert_not_called()

    def test_mcp_global_sem_entrada_nao_executa(self):
        self.perguntar.side_effect = EOFError
        codigo, _, erro = rodar("instalar", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.executar.assert_not_called()

    def test_mcp_global_simulado_nao_pergunta_nem_executa(self):
        self.perguntar.return_value = "s"
        codigo, saida, erro = rodar("instalar", str(self.projeto), "--mcp-global", "--simular")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("MCP global (rode uma vez):", saida)
        self.assertEqual(list(self.projeto.iterdir()), [])
        self.perguntar.assert_not_called()
        self.executar.assert_not_called()

    def test_sem_mcp_omite_comandos_e_confirmacao(self):
        _, saida, _ = rodar("instalar", str(self.projeto), "--mcp-global", "--sem-mcp")
        self.assertNotIn("mcp add", saida)
        self.perguntar.assert_not_called()
        self.executar.assert_not_called()

    def test_mcp_global_executavel_ausente_vira_aviso(self):
        self.perguntar.return_value = "s"
        with unittest.mock.patch.object(kit.shutil, "which", return_value=None), \
                unittest.mock.patch.object(kit.glob, "glob", return_value=[]):
            codigo, saida, erro = rodar("instalar", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("codex não encontrado", saida)
        self.assertIn("agy não encontrado", saida)
        self.executar.assert_not_called()

    def test_mcp_global_falha_vira_aviso_e_continua(self):
        self.perguntar.return_value = "s"
        self.executar.side_effect = [unittest.mock.Mock(returncode=7), unittest.mock.Mock(returncode=0)]
        with unittest.mock.patch.object(kit.shutil, "which", side_effect=lambda nome: nome):
            codigo, saida, erro = rodar("instalar", str(self.projeto), "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("codex falhou com código de saída 7", saida)
        self.assertEqual(self.executar.call_count, 2)

    def test_mcp_global_erro_ao_iniciar_vira_aviso(self):
        self.perguntar.return_value = "s"
        self.executar.side_effect = OSError("executável indisponível")
        with unittest.mock.patch.object(kit.shutil, "which", return_value="codex"):
            codigo, saida, erro = rodar("instalar", str(self.projeto), "--agentes", "codex", "--mcp-global")
        self.assertEqual(codigo, 0, erro)
        self.assertIn("não foi possível executar codex", saida)

    def test_mescla_settings_do_gemini_existente(self):
        settings = self.projeto / ".gemini/settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"theme": "escuro", "context": {"fileName": "GEMINI.md"}}), encoding="utf-8")

        rodar("instalar", str(self.projeto), "--agentes", "gemini")

        dados = self.ler_json(".gemini/settings.json")
        self.assertEqual(dados["theme"], "escuro")
        self.assertEqual(dados["context"]["fileName"], "GEMINI.md")  # escolha do usuário mantida
        self.assertIn("context7", dados["mcpServers"])

    def test_json_invalido_vira_mensagem(self):
        (self.projeto / ".mcp.json").write_text("{ // comentário\n}", encoding="utf-8")
        codigo, _, erro = rodar("instalar", str(self.projeto), "--agentes", "claude")
        self.assertEqual(codigo, 1)
        self.assertIn("não é um JSON válido", erro)

    def test_destino_inexistente_e_erro(self):
        codigo, _, erro = rodar("instalar", str(self.projeto / "nao-existe"))
        self.assertEqual(codigo, 1)
        self.assertIn("não existe", erro)


class NovaSkillTest(unittest.TestCase):
    def test_cria_skill_valida(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = kit.PASTA_SKILLS
            kit.PASTA_SKILLS = Path(tmp)
            try:
                codigo, _, erro = rodar("nova-skill", "gerar-changelog", "--descricao", "Gera. Use quando X.")
                self.assertEqual(codigo, 0, erro)
                self.assertEqual(kit.problemas_da_skill(Path(tmp) / "gerar-changelog"), [])
                codigo, _, erro = rodar("nova-skill", "Nome Invalido")
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
        dados = json.dumps(resposta).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args):
        pass


class ExecutarTest(unittest.TestCase):
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
        codigo, saida, erro = rodar("executar", "revisar", "--entrada", "diff aqui",
                                    "--url", self.url, "--modelo", "falso", "--protocolo", "openai")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(saida.strip(), "resposta openai")
        req = ProvedorFalso.ultima
        self.assertEqual(req["caminho"], "/v1/chat/completions")
        mensagens = req["corpo"]["messages"]
        self.assertIn("# Revisar um diff", mensagens[0]["content"])
        self.assertEqual(mensagens[1], {"role": "user", "content": "diff aqui"})

    def test_protocolo_anthropic(self):
        with unittest.mock.patch.dict("os.environ", {"KIT_IA_CHAVE": "chave-teste"}):
            codigo, saida, erro = rodar("executar", "planejar", "--entrada", "pedido",
                                        "--url", self.url, "--modelo", "m", "--protocolo", "anthropic")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(saida.strip(), "resposta anthropic")
        req = ProvedorFalso.ultima
        self.assertEqual(req["caminho"], "/v1/messages")
        self.assertEqual(req["cabecalhos"]["x-api-key"], "chave-teste")
        self.assertIn("# Planejar uma mudança", req["corpo"]["system"])

    def test_registra_uso_dos_protocolos_sem_chave_ou_conversa(self):
        for protocolo, entrada, saida, custo in (("openai", 30, 10, .001), ("anthropic", 20, 8, None)):
            with self.subTest(protocolo=protocolo), unittest.mock.patch.dict(os.environ, {"KIT_IA_CHAVE": "segredo-nao-gravar"}):
                codigo, _, erro = rodar("executar", "revisar", "--entrada", "conteudo-nao-gravar",
                    "--url", self.url, "--modelo", "falso", "--protocolo", protocolo, "--task", "BL-LU-3")
                self.assertEqual(codigo, 0, erro)
                texto = (Path(self.temporaria.name) / "uso.jsonl").read_text(encoding="utf-8")
                registro = json.loads(texto.splitlines()[-1])
                self.assertEqual((registro["entrada"], registro["saida"], registro["custo_usd"]), (entrada, saida, custo))
                self.assertEqual(registro["task"], "BL-LU-3")
                self.assertGreaterEqual(registro["duracao_segundos"], 0)
                self.assertNotIn("segredo-nao-gravar", texto)
                self.assertNotIn("conteudo-nao-gravar", texto)
                self.assertNotIn("resposta openai", texto)

    def test_falha_de_registro_so_avisa(self):
        with unittest.mock.patch("kit.custo.registrar_uso", side_effect=OSError("disco indisponível")):
            codigo, saida, erro = rodar("executar", "revisar", "--entrada", "x", "--url", self.url, "--protocolo", "openai")
        self.assertEqual(codigo, 0)
        self.assertIn("resposta openai", saida)
        self.assertIn("aviso:", erro)

    def test_telemetria_malformada_preserva_resposta_valida(self):
        codigo, saida, erro = rodar("executar", "revisar", "--entrada", "x", "--url", self.url,
                                    "--modelo", "telemetria-invalida", "--protocolo", "openai")
        self.assertEqual(codigo, 0)
        self.assertEqual(saida.strip(), "resposta openai")
        self.assertIn("aviso: telemetria de uso inválida", erro)
        self.assertNotIn("Traceback", erro)
        self.assertFalse((Path(self.temporaria.name) / "uso.jsonl").exists())

    def test_custo_cli_sem_fontes_e_erro_de_data(self):
        with unittest.mock.patch("kit.custo.coletar", return_value=([], [])):
            codigo, saida, _ = rodar("custo", "--json")
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(saida)["grupos"], [])
            self.assertEqual(rodar("custo", "--desde", "invalida")[0], 1)

    def test_provedor_fora_do_ar_vira_mensagem(self):
        codigo, _, erro = rodar("executar", "revisar", "--entrada", "x",
                                "--url", "http://127.0.0.1:1/v1", "--protocolo", "openai")
        self.assertEqual(codigo, 1)
        self.assertIn("não consegui conectar", erro)
        registro = json.loads((Path(self.temporaria.name) / "uso.jsonl").read_text(encoding="utf-8"))
        self.assertIsNone(registro["entrada"])
        self.assertGreaterEqual(registro["duracao_segundos"], 0)

    def test_skill_inexistente_e_erro(self):
        codigo, _, erro = rodar("executar", "nao-existe", "--entrada", "x")
        self.assertEqual(codigo, 1)
        self.assertIn("não encontrada", erro)

    def test_entrada_de_arquivo_e_de_pipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "mudanca.diff"
            arquivo.write_text("conteúdo do arquivo", encoding="utf-8")
            rodar("executar", "revisar", "--entrada", str(arquivo), "--url", self.url, "--protocolo", "openai")
        self.assertEqual(ProvedorFalso.ultima["corpo"]["messages"][1]["content"], "conteúdo do arquivo")

        with unittest.mock.patch("sys.stdin", io.StringIO("diff via pipe")):
            codigo, _, erro = rodar("executar", "revisar", "--url", self.url, "--protocolo", "openai")
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(ProvedorFalso.ultima["corpo"]["messages"][1]["content"], "diff via pipe")

    def test_recusa_do_modelo_vira_erro(self):
        with unittest.mock.patch.dict("os.environ", {"KIT_IA_CHAVE": "k"}):
            codigo, _, erro = rodar("executar", "revisar", "--entrada", "x", "--url", self.url,
                                    "--protocolo", "anthropic", "--modelo", "recusa")
        self.assertEqual(codigo, 1)
        self.assertIn("recusou", erro)

    def test_erro_http_do_provedor_vira_mensagem(self):
        codigo, _, erro = rodar("executar", "revisar", "--entrada", "x", "--url", self.url,
                                "--protocolo", "openai", "--modelo", "nao-autorizado")
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
