#!/usr/bin/env python3
"""
dev-amys-ai (kit-ia): um kit de IA para desenvolvimento, agnóstico de modelo e de agente.

O kit mantém UMA fonte de skills (skills/), de processo de trabalho (processo/), de padrões
técnicos (padroes/), de instruções (AGENTS.md) e de servidores MCP (config/mcp.json), e
instala tudo em qualquer projeto, no formato que cada agente entende (Claude Code, Codex,
Cursor, Copilot, Gemini, OpenCode...).
Também executa uma skill direto em qualquer modelo (Ollama, OpenRouter, OpenAI, Claude...).

Só usa a biblioteca padrão do Python de propósito: o kit precisa rodar em qualquer
máquina e em qualquer CI, sem `pip install`.

Uso rápido:
    python kit.py list
    python kit.py validate
    python kit.py install ../meu-projeto --dry-run
    python kit.py install --global
    python kit.py new-skill gerar-changelog --description "Gera ... Use quando ..."
    git diff | python kit.py run revisar
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import custo

if os.name == "nt":
    import msvcrt
else:
    import fcntl

VERSAO = "0.3.0"

RAIZ = Path(__file__).resolve().parent
PASTA_SKILLS = RAIZ / "skills"
PASTA_TEMPLATES = RAIZ / "templates"
ARQUIVO_AGENTES = RAIZ / "config" / "agentes.json"
ARQUIVO_MCP = RAIZ / "config" / "mcp.json"
ARQUIVO_ENV = RAIZ / ".env"

# Pasta do kit dentro de cada projeto. Guarda as cópias do processo, dos padrões e dos
# modelos (gerenciadas pelo kit) e o projeto.yaml (do projeto: o kit nunca sobrescreve).
PASTA_NO_PROJETO = ".kit-ia"
PASTAS_COPIADAS = ("processo", "padroes", "modelos")
REFERENCIA_NUCLEO = f"{PASTA_NO_PROJETO}/processo/00-nucleo.md"

# Arquivos Markdown cujos links relativos o `validate` confere.
ARQUIVOS_COM_LINKS = ("README.md", "AGENTS.md", "CHANGELOG.md", "processo/*.md", "padroes/*.md",
                      "modelos/**/*.md", "docs/*.md", "skills/*/*.md")

# O modelo de AGENTS.md vive dentro da skill que o usa: assim existe uma única cópia,
# e a skill instalada num projeto continua tendo o modelo ao lado dela.
MODELO_AGENTS_MD = PASTA_SKILLS / "iniciar-agents-md" / "modelo-AGENTS.md"

# Arquivo que marca uma pasta de skill como "instalada pelo kit". Sem ele, a pasta é do
# usuário (ex.: uma skill `verificar` própria do projeto) e o kit não sobrescreve.
MARCADOR = ".kit-ia"

# Regras do padrão aberto Agent Skills (agentskills.io) para o frontmatter.
PADRAO_NOME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NOME = 64
MAX_DESCRICAO = 1024


class ErroKit(Exception):
    """Erro esperado (entrada inválida, arquivo ausente): vira mensagem, não stack trace."""


# =============================================================== utilidades

def ler_json(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        raise ErroKit(
            f"{caminho} não é um JSON válido ({erro}). "
            "Se o arquivo tiver comentários (JSONC), faça a mescla à mão."
        ) from erro


def ler_frontmatter(texto: str) -> tuple[dict, str]:
    """Separa o frontmatter (entre linhas '---') do corpo de um SKILL.md.

    Sem biblioteca YAML de propósito (zero dependências): o kit lê o formato simples
    `chave: valor`, uma chave por linha. Linhas indentadas (metadados aninhados) são ignoradas.
    """
    linhas = texto.splitlines()
    if not linhas or linhas[0].strip() != "---":
        raise ErroKit("o arquivo não começa com '---' (falta o frontmatter)")
    fim = next((i for i in range(1, len(linhas)) if linhas[i].strip() == "---"), None)
    if fim is None:
        raise ErroKit("frontmatter sem o '---' de fechamento")

    dados: dict[str, str] = {}
    for linha in linhas[1:fim]:
        if not linha.strip() or linha.lstrip().startswith("#") or linha[0] in " \t":
            continue
        chave, separador, valor = linha.partition(":")
        if not separador:
            raise ErroKit(f"linha inválida no frontmatter: {linha!r}")
        dados[chave.strip()] = valor.strip().strip('"').strip("'")
    corpo = "\n".join(linhas[fim + 1:]).strip()
    return dados, corpo


def lista_csv(texto: str | None) -> list[str] | None:
    if not texto:
        return None
    return [item.strip() for item in texto.split(",") if item.strip()]


# =============================================================== skills

def problemas_da_skill(pasta: Path) -> list[str]:
    """Confere uma skill contra o padrão Agent Skills. Lista vazia = skill válida."""
    arquivo = pasta / "SKILL.md"
    if not arquivo.is_file():
        return ["falta o arquivo SKILL.md"]
    try:
        dados, corpo = ler_frontmatter(arquivo.read_text(encoding="utf-8"))
    except ErroKit as erro:
        return [str(erro)]

    problemas = []
    nome = dados.get("name", "")
    descricao = dados.get("description", "")
    if not nome:
        problemas.append("frontmatter sem 'name'")
    elif nome != pasta.name:
        problemas.append(f"'name' ({nome}) precisa ser igual ao nome da pasta ({pasta.name})")
    elif len(nome) > MAX_NOME or not PADRAO_NOME.match(nome):
        problemas.append(f"'name' inválido: use minúsculas, números e hífen, até {MAX_NOME} caracteres")
    if not descricao:
        problemas.append("frontmatter sem 'description' (é por ela que o agente decide usar a skill)")
    elif len(descricao) > MAX_DESCRICAO:
        problemas.append(f"'description' com {len(descricao)} caracteres (máximo {MAX_DESCRICAO})")
    if not corpo:
        problemas.append("corpo vazio: a skill não tem instruções")
    return problemas


def pastas_de_skills() -> list[Path]:
    if not PASTA_SKILLS.is_dir():
        return []
    return sorted(p for p in PASTA_SKILLS.iterdir() if p.is_dir() and not p.name.startswith("."))


def descricao_da_skill(pasta: Path) -> str:
    try:
        dados, _ = ler_frontmatter((pasta / "SKILL.md").read_text(encoding="utf-8"))
        return dados.get("description", "")
    except (OSError, ErroKit):
        return "(inválida: rode `python kit.py validate`)"


def selecionar_skills(nomes: list[str] | None) -> list[Path]:
    todas = {p.name: p for p in pastas_de_skills()}
    if not nomes:
        return list(todas.values())
    desconhecidas = [n for n in nomes if n not in todas]
    if desconhecidas:
        raise ErroKit(f"skill(s) inexistente(s): {', '.join(desconhecidas)}. Disponíveis: {', '.join(todas)}")
    return [todas[n] for n in nomes]


# =============================================================== agentes e MCP

def carregar_agentes() -> dict:
    return ler_json(ARQUIVO_AGENTES)["agentes"]


def selecionar_agentes(nomes: list[str] | None) -> dict:
    agentes = carregar_agentes()
    if not nomes:
        return agentes
    desconhecidos = [n for n in nomes if n not in agentes]
    if desconhecidos:
        raise ErroKit(f"agente(s) desconhecido(s): {', '.join(desconhecidos)}. Disponíveis: {', '.join(agentes)}")
    return {n: agentes[n] for n in nomes}


def carregar_servidores() -> dict:
    servidores = ler_json(ARQUIVO_MCP).get("servidores", {})
    for nome, s in servidores.items():
        if s.get("tipo") == "http" and not s.get("url"):
            raise ErroKit(f"config/mcp.json: o servidor '{nome}' é http e precisa de 'url'")
        if s.get("tipo") == "stdio" and not s.get("comando"):
            raise ErroKit(f"config/mcp.json: o servidor '{nome}' é stdio e precisa de 'comando'")
        if s.get("tipo") not in ("http", "stdio"):
            raise ErroKit(f"config/mcp.json: o servidor '{nome}' precisa de \"tipo\": \"http\" ou \"stdio\"")
    return servidores


# Em qual chave do arquivo de configuração cada formato guarda os servidores.
CHAVE_DOS_SERVIDORES = {
    "claude": "mcpServers",
    "cursor": "mcpServers",
    "gemini": "mcpServers",
    "vscode": "servers",
    "opencode": "mcp",
}


def converter_servidor(formato: str, s: dict) -> dict:
    """Traduz um servidor do formato do kit para o formato de um agente.

    É aqui que mora a "agnosticidade" do MCP: o protocolo é o mesmo para todos,
    só o arquivo de configuração muda de agente para agente.
    """
    http = s["tipo"] == "http"
    cabecalhos = s.get("cabecalhos") or {}
    stdio = {"command": s.get("comando"), "args": s.get("args", [])}
    if s.get("env"):
        stdio["env"] = s["env"]

    if formato in ("claude", "vscode"):
        d = {"type": "http", "url": s["url"]} if http else {"type": "stdio", **stdio}
        if http and cabecalhos:
            d["headers"] = cabecalhos
    elif formato == "cursor":
        d = {"url": s["url"]} if http else dict(stdio)
        if http and cabecalhos:
            d["headers"] = cabecalhos
    elif formato == "gemini":
        d = {"httpUrl": s["url"]} if http else dict(stdio)
        if http and cabecalhos:
            d["headers"] = cabecalhos
    elif formato == "opencode":
        if http:
            d = {"type": "remote", "url": s["url"], "enabled": True}
            if cabecalhos:
                d["headers"] = cabecalhos
        else:
            d = {"type": "local", "command": [s["comando"], *s.get("args", [])], "enabled": True}
            if s.get("env"):
                d["environment"] = s["env"]
    else:
        raise ErroKit(f"formato de MCP desconhecido em config/agentes.json: {formato}")
    return d


def comandos_mcp_global(formato: str, servidores: dict) -> list[list[str]]:
    """Gera argumentos sem efeitos externos; cabeçalhos do Codex exigem ajuste manual."""
    executaveis = {"comando-codex": "codex", "comando-antigravity": "agy"}
    if formato not in executaveis:
        raise ErroKit(f"formato de MCP global desconhecido em config/agentes.json: {formato}")
    comandos = []
    for nome, servidor in servidores.items():
        codex = formato == "comando-codex"
        if codex and servidor.get("cabecalhos"):
            continue
        comando = [executaveis[formato], "mcp", "add"]
        if codex:
            comando.append(nome)
        if not codex:
            for chave, valor in (servidor.get("cabecalhos") or {}).items():
                comando.extend(["--header", f"{chave}: {valor}"])
        for chave, valor in (servidor.get("env") or {}).items():
            comando.extend(["--env", f"{chave}={valor}"])
        if not codex:
            comando.append(nome)
        if servidor["tipo"] == "http":
            if codex:
                comando.append("--url")
            comando.append(servidor["url"])
        else:
            comando.extend(["--", servidor["comando"], *servidor.get("args", [])])
        comandos.append(comando)
    return comandos


def comando_legivel(comando: list[str]) -> str:
    """Aspas preservam argumentos com espaços e variáveis literais ao copiar o comando."""
    if os.name == "nt":  # PowerShell: apóstrofo literal é duplicado dentro das aspas simples.
        return " ".join(
            argumento if re.fullmatch(r"[\w@%+=:,./-]+", argumento)
            else "'" + argumento.replace("'", "''") + "'"
            for argumento in comando
        )
    return shlex.join(comando)


def localizar_executavel(nome: str, alternativas: list[str]) -> str | None:
    encontrado = shutil.which(nome)
    if encontrado:
        return encontrado
    for alternativa in alternativas:
        padrao = os.path.expanduser(os.path.expandvars(alternativa))
        for caminho in sorted(glob.glob(padrao), reverse=True):
            if Path(caminho).is_file():
                return caminho
    return None


# =============================================================== execução (com --dry-run)

class Execucao:
    """Faz (ou só mostra, com --dry-run) cada mudança no disco, e conta o que mudou."""

    def __init__(self, simular: bool):
        self.simular = simular
        self.mudancas = 0
        self.avisos = 0

    def _relatar(self, simbolo: str, texto: str):
        print(f"  {simbolo} {texto}")

    def aviso(self, texto: str):
        self.avisos += 1
        self._relatar("!", texto)

    def escrever(self, caminho: Path, conteudo: str):
        if caminho.is_file() and caminho.read_text(encoding="utf-8") == conteudo:
            self._relatar("=", f"{caminho} (sem mudanças)")
            return
        self._relatar("+", f"{'atualizar' if caminho.exists() else 'criar'} {caminho}")
        self.mudancas += 1
        if not self.simular:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_text(conteudo, encoding="utf-8", newline="\n")

    def copiar_pasta(self, origem: Path, destino: Path, forcar: bool):
        """Copia uma pasta gerenciada pelo kit (skill, processo, padrões, modelos).

        Pasta sem o MARCADOR é do usuário: só é trocada com --force.
        Pasta com o MARCADOR é cópia do kit: é atualizada sempre (edições à mão se perdem,
        e é de propósito: regra própria do projeto vai no AGENTS.md ou no projeto.yaml).
        """
        if destino.exists():
            if not (destino / MARCADOR).exists() and not forcar:
                self.aviso(f"{destino} já existe e não foi instalada pelo kit: mantida (use --force para trocar)")
                return
            if pastas_iguais(origem, destino):
                self._relatar("=", f"{destino} (sem mudanças)")
                return
        self._relatar("+", f"{'atualizar' if destino.exists() else 'criar'} {destino}")
        self.mudancas += 1
        if not self.simular:
            if destino.exists():
                shutil.rmtree(destino)
            shutil.copytree(origem, destino, ignore=shutil.ignore_patterns("__pycache__", MARCADOR))
            (destino / MARCADOR).write_text(
                "Copiada pelo dev-amys-ai (kit-ia). Não edite esta cópia: ela é substituída a cada\n"
                "instalação. Edite a fonte no kit, ou ponha a regra do projeto no AGENTS.md.\n",
                encoding="utf-8",
            )


def pastas_iguais(a: Path, b: Path) -> bool:
    def conteudo(pasta: Path) -> dict:
        return {
            p.relative_to(pasta).as_posix(): p.read_bytes()
            for p in pasta.rglob("*")
            if p.is_file() and p.name != MARCADOR and "__pycache__" not in p.parts
        }
    return conteudo(a) == conteudo(b)


# =============================================================== instalar

def instalar_mcp_json(ex: Execucao, caminho: Path, formato: str, servidores: dict, forcar: bool):
    dados = ler_json(caminho) if caminho.exists() else {}
    if formato == "opencode" and not dados:
        dados["$schema"] = "https://opencode.ai/config.json"
    container = dados.setdefault(CHAVE_DOS_SERVIDORES[formato], {})
    for nome, servidor in servidores.items():
        if nome in container and not forcar:
            if container[nome] != converter_servidor(formato, servidor):
                ex.aviso(f"{caminho}: já tem o servidor '{nome}' com outra configuração; mantido (use --force)")
            continue
        container[nome] = converter_servidor(formato, servidor)
    if formato == "gemini":
        # O Gemini CLI lê GEMINI.md por padrão; isto faz ele ler também o AGENTS.md.
        dados.setdefault("context", {}).setdefault("fileName", ["AGENTS.md", "GEMINI.md"])
    ex.escrever(caminho, json.dumps(dados, indent=2, ensure_ascii=False) + "\n")


def instalar_mcp_global(ex: Execucao, configuracoes: list[dict], servidores: dict, executar: bool,
                       remover: bool = False):
    print("\nMCP global (rode uma vez):")
    pendentes = []
    for mcp in configuracoes:
        formato = mcp["formato"]
        if formato == "comando-codex" and not remover:
            for nome, servidor in servidores.items():
                if servidor.get("cabecalhos"):
                    ex.aviso(f"Codex: servidor '{nome}' tem cabeçalhos; configure à mão")
        comandos = comandos_mcp_global(formato, servidores)
        if remover:
            # A configuração central continua sendo a fonte dos executáveis e servidores.
            executavel = {"comando-codex": "codex", "comando-antigravity": "agy"}[formato]
            comandos = [[executavel, "mcp", "remove", nome] for nome in servidores]
        for comando in comandos:
            print(f"  {comando_legivel(comando)}")
            pendentes.append((comando, mcp.get("executaveis_alternativos", [])))

    # A simulação nem pergunta: aceitar por engano nunca deve alterar o perfil do usuário.
    if not executar or ex.simular or not pendentes:
        return
    try:
        resposta = input("Executar estes comandos? [s/N] ")
    except EOFError:
        resposta = ""
    if resposta.strip().lower() != "s":
        return
    for comando, alternativas in pendentes:
        executavel = localizar_executavel(comando[0], alternativas)
        if not executavel:
            ex.aviso(f"{comando[0]} não encontrado; comando não executado")
            continue
        try:
            # Lista de argumentos, sem shell: espaços e metacaracteres continuam sendo dados.
            resultado = subprocess.run([executavel, *comando[1:]], check=False)
        except OSError as erro:
            ex.aviso(f"não foi possível executar {comando[0]}: {erro}")
            continue
        if resultado.returncode:
            ex.aviso(f"{comando[0]} falhou com código de saída {resultado.returncode}")
        else:
            ex.mudancas += 1


def instalar(args) -> Execucao:
    agentes = selecionar_agentes(lista_csv(args.agentes))
    skills = selecionar_skills(lista_csv(args.skills))
    ex = Execucao(args.simular)
    prefixo = "[simulação] " if args.simular else ""

    if args.global_:
        print(f"{prefixo}Instalando {len(skills)} skill(s) no nível do usuário (vale para todos os projetos):")
        destinos = {Path(cfg["skills_global"]).expanduser() for cfg in agentes.values() if cfg.get("skills_global")}
    else:
        if not args.destino:
            raise ErroKit("informe a pasta do projeto (ex.: python kit.py install ../meu-projeto) ou use --global")
        base = Path(args.destino).expanduser().resolve()
        if not base.is_dir():
            raise ErroKit(f"a pasta {base} não existe")
        print(f"{prefixo}Instalando em {base}")
        destinos = {base / cfg["skills"] for cfg in agentes.values() if cfg.get("skills")}

    print("\nSkills:")
    for pasta_destino in sorted(destinos):
        for skill in skills:
            ex.copiar_pasta(skill, pasta_destino / skill.name, args.forcar)

    if args.global_:
        print("\nNo modo --global só as skills são instaladas. Para configurar MCP, informe a pasta do projeto.")
    else:
        print(f"\nProcesso, padrões e configuração ({PASTA_NO_PROJETO}/):")
        pasta_kit = base / PASTA_NO_PROJETO
        for nome in PASTAS_COPIADAS:
            ex.copiar_pasta(RAIZ / nome, pasta_kit / nome, args.forcar)
        ex.escrever(pasta_kit / "VERSAO", f"{VERSAO}\n")
        projeto_yaml = pasta_kit / "projeto.yaml"
        if projeto_yaml.exists():
            print(f"  = {projeto_yaml} (do projeto, mantido)")
        else:
            modelo = (PASTA_TEMPLATES / "projeto.yaml").read_text(encoding="utf-8")
            ex.escrever(projeto_yaml, modelo.replace("{{nome}}", base.name))
            print("    -> ajuste áreas, branches, destinos e comandos do projeto")

        print("\nInstruções:")
        agents_md = base / "AGENTS.md"
        if agents_md.exists():
            if REFERENCIA_NUCLEO in agents_md.read_text(encoding="utf-8"):
                print(f"  = {agents_md} (já existe e aponta o processo)")
            else:
                ex.aviso(
                    f"{agents_md} existe e não aponta o processo: acrescente a seção 'Como trabalhar' "
                    f"que manda ler {REFERENCIA_NUCLEO} (modelo em skills/iniciar-agents-md/modelo-AGENTS.md)"
                )
        else:
            ex.escrever(agents_md, MODELO_AGENTS_MD.read_text(encoding="utf-8"))
            print("    -> preencha com a skill `iniciar-agents-md` (peça ao agente: \"preencha o AGENTS.md\")")
        if "claude" in agentes:
            claude_md = base / "CLAUDE.md"
            if not claude_md.exists():
                ex.escrever(claude_md, (PASTA_TEMPLATES / "CLAUDE.md").read_text(encoding="utf-8"))
            elif "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
                ex.aviso(f"{claude_md} existe e não importa o AGENTS.md: acrescente a linha '@AGENTS.md' no topo")
            else:
                print(f"  = {claude_md} (já importa o AGENTS.md)")

        if not args.sem_mcp:
            print("\nServidores MCP:")
            servidores = carregar_servidores()
            globais = []
            for cfg in agentes.values():
                mcp = cfg.get("mcp")
                if not mcp:
                    continue
                if mcp["formato"].startswith("comando-"):
                    globais.append(mcp)
                else:
                    caminho = base / mcp["arquivo"]
                    instalar_mcp_json(ex, caminho, mcp["formato"], servidores, args.forcar)
            if globais:
                instalar_mcp_global(ex, globais, servidores, args.mcp_global)

        if not args.simular:
            registrar_projeto(base, list(agentes), lista_csv(args.skills), args.sem_mcp)

    verbo = "seriam feitas" if args.simular else "feitas"
    print(f"\n{ex.mudancas} mudança(s) {verbo}, {ex.avisos} aviso(s).")
    return ex


def cmd_instalar(args) -> int:
    instalar(args)
    return 0


# =============================================================== desinstalação

def caminho_sem_desvios(caminho: Path, limite: Path) -> bool:
    """Não siga links ou junções: um marcador fora do destino não autoriza remoção."""
    if caminho == limite or not caminho.is_relative_to(limite):
        return False
    try:
        for parte in (caminho, *caminho.parents):
            if parte.is_symlink():
                return False
            try:
                atributos = parte.lstat()
            except FileNotFoundError:
                continue
            # isjunction só existe desde 3.12; lstat expõe reparse points também
            # no Windows com Python 3.10/3.11, sem seguir a junção.
            if getattr(atributos, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return False
        fisico = caminho.resolve()
        raiz_fisica = limite.resolve()
        return fisico != raiz_fisica and fisico.is_relative_to(raiz_fisica)
    except (OSError, RuntimeError, ValueError):
        # Sem comprovar o destino físico, a remoção não está autorizada.
        return False


def planejar_remocao_mcp(ex: Execucao, caminho: Path, formato: str, servidores: dict,
                         acoes: dict):
    if not caminho.is_file():
        return
    try:
        dados = ler_json(caminho)
    except (ErroKit, OSError, UnicodeError) as erro:
        ex.aviso(f"{caminho}: mantido; {erro}")
        return
    if not isinstance(dados, dict):
        ex.aviso(f"{caminho}: mantido; o JSON precisa ser um objeto")
        return
    original = json.dumps(dados, ensure_ascii=False)
    chave = CHAVE_DOS_SERVIDORES[formato]
    container = dados.get(chave)
    if isinstance(container, dict):
        removido = False
        for nome, servidor in servidores.items():
            if nome not in container:
                continue
            if container[nome] == converter_servidor(formato, servidor):
                del container[nome]
                removido = True
            else:
                ex.aviso(f"{caminho}: servidor '{nome}' alterado, mantido")
        if removido and not container:
            dados.pop(chave)
    contexto = dados.get("context")
    if formato == "gemini" and isinstance(contexto, dict):
        if contexto.get("fileName") == ["AGENTS.md", "GEMINI.md"]:
            del contexto["fileName"]
            if not contexto:
                del dados["context"]
    if json.dumps(dados, ensure_ascii=False) != original:
        acoes[caminho] = (json.dumps(dados, indent=2, ensure_ascii=False) + "\n"
                           if dados.keys() - {"$schema"} else None)


def desinstalar(args) -> int:
    agentes = selecionar_agentes(lista_csv(args.agentes))
    ex = Execucao(args.simular)
    acoes: dict[Path, str | None] = {}
    if args.global_:
        if args.destino:
            raise ErroKit("use a pasta do projeto ou --global, não ambos")
        destinos = {Path(cfg["skills_global"]).expanduser().absolute()
                    for cfg in agentes.values() if cfg.get("skills_global")}
        base = None
        projetos = {}
    else:
        if not args.destino:
            raise ErroKit("informe a pasta do projeto ou use --global")
        base = Path(args.destino).expanduser().resolve()
        if not base.is_dir():
            raise ErroKit(f"a pasta {base} não existe")
        projetos = carregar_projetos()
        destinos = {base / cfg["skills"] for cfg in agentes.values() if cfg.get("skills")}

    def seguro(caminho, limite):
        if caminho_sem_desvios(caminho, limite):
            return True
        ex.aviso(f"{caminho}: caminho com link, junção ou fora do destino; mantido")
        return False

    for destino in sorted(destinos):
        limite = base if base else destino.parent
        if not seguro(destino, limite) or not destino.is_dir():
            continue
        for pasta in sorted(destino.iterdir()):
            if (seguro(pasta, limite) and pasta.is_dir()
                    and (pasta / MARCADOR).is_file() and not (pasta / MARCADOR).is_symlink()):
                acoes[pasta] = None

    if base:
        pasta_kit = base / PASTA_NO_PROJETO
        for nome in PASTAS_COPIADAS:
            pasta = pasta_kit / nome
            if (seguro(pasta, base) and pasta.is_dir()
                    and (pasta / MARCADOR).is_file() and not (pasta / MARCADOR).is_symlink()):
                acoes[pasta] = None
        versao_instalada = projetos.get(str(base), {}).get("versao", VERSAO)
        modelos = {
            pasta_kit / "VERSAO": f"{versao_instalada}\n",
            pasta_kit / "projeto.yaml": (PASTA_TEMPLATES / "projeto.yaml").read_text(encoding="utf-8").replace("{{nome}}", base.name),
            base / "AGENTS.md": MODELO_AGENTS_MD.read_text(encoding="utf-8"),
        }
        if "claude" in agentes:
            modelos[base / "CLAUDE.md"] = (PASTA_TEMPLATES / "CLAUDE.md").read_text(encoding="utf-8")
        for caminho, modelo in modelos.items():
            if not seguro(caminho, base) or not caminho.is_file():
                continue
            if caminho.read_bytes() == modelo.encode("utf-8"):
                acoes[caminho] = None
            else:
                secao = {"AGENTS.md": "a seção 'Como trabalhar' que aponta .kit-ia/",
                         "CLAUDE.md": "a linha '@AGENTS.md' e a referência a .kit-ia/"}.get(caminho.name)
                ex.aviso(f"{caminho}: editado, mantido" + (f"; pode remover à mão {secao}" if secao else ""))
        servidores = carregar_servidores()
        globais = []
        for cfg in agentes.values():
            mcp = cfg.get("mcp")
            if not mcp:
                continue
            if mcp["formato"].startswith("comando-"):
                globais.append(mcp)
            else:
                caminho = base / mcp["arquivo"]
                if seguro(caminho, base):
                    planejar_remocao_mcp(ex, caminho, mcp["formato"], servidores, acoes)
    else:
        globais = []
        servidores = {}

    print("\nDesinstalação (simulação):" if args.simular else "\nDesinstalação:")
    for caminho, conteudo in acoes.items():
        print(f"  {'remover' if conteudo is None else 'remover entradas do kit em'} {caminho}")
    registrado = base is not None and str(base) in projetos
    if registrado:
        print(f"  remover {base} do registro de projetos")
    # A prévia inclui também os pais que ficarão vazios. Diretórios do usuário com
    # qualquer outro conteúdo sobrevivem; a remoção real sempre confere novamente.
    pais = set()
    for caminho, conteudo in acoes.items():
        if conteudo is not None:
            continue
        limite = base if base else next(d.parent for d in destinos if caminho.is_relative_to(d))
        for pai in caminho.parents:
            if pai == limite:
                break
            pais.add(pai)
    vazios = set()
    for pai in sorted(pais, key=lambda p: len(p.parts), reverse=True):
        if pai.is_dir() and all(filho in vazios or (filho in acoes and acoes[filho] is None)
                               for filho in pai.iterdir()):
            vazios.add(pai)
            print(f"  remover pasta vazia {pai}")
    if globais:
        instalar_mcp_global(ex, globais, servidores, False, remover=True)
    originais = {caminho: caminho.read_bytes() for caminho in acoes if caminho.is_file()}
    if args.simular:
        return 0
    if not args.yes:
        try:
            resposta = input("Remover? [s/N] ")
        except EOFError:
            resposta = ""
        if resposta.strip().lower() != "s":
            print("Remoção cancelada.")
            return 0
    try:
        for caminho, conteudo in acoes.items():
            limite = base if base else next(d.parent for d in destinos if caminho.is_relative_to(d))
            if not seguro(caminho, limite):
                continue
            if caminho in originais and (not caminho.is_file() or caminho.read_bytes() != originais[caminho]):
                ex.aviso(f"{caminho}: mudou depois da prévia, mantido")
                continue
            if conteudo is not None:
                ex.escrever(caminho, conteudo)
            elif caminho.is_dir():
                if not (caminho / MARCADOR).is_file() or (caminho / MARCADOR).is_symlink():
                    ex.aviso(f"{caminho}: marcador ausente depois da prévia, mantido")
                    continue
                shutil.rmtree(caminho)
            else:
                caminho.unlink()
        for pai in sorted(vazios, key=lambda p: len(p.parts), reverse=True):
            limite = base if base else next(d.parent for d in destinos if pai == d or pai.is_relative_to(d))
            if seguro(pai, limite) and pai.is_dir() and not any(pai.iterdir()):
                pai.rmdir()
        if registrado:
            with bloquear_projetos():
                atuais = carregar_projetos()
                atuais.pop(str(base), None)
                salvar_projetos(atuais)
    except OSError as erro:
        raise ErroKit(f"não foi possível concluir a desinstalação: {erro}") from erro
    if globais and args.mcp_global:
        instalar_mcp_global(ex, globais, servidores, True, remover=True)
    return 0


def cmd_desinstalar(args) -> int:
    try:
        return desinstalar(args)
    except (OSError, UnicodeError) as erro:
        raise ErroKit(f"não foi possível concluir a desinstalação: {erro}") from erro


# =============================================================== projetos / atualização

def arquivo_projetos() -> Path:
    return custo.pasta_env("KIT_IA_HOME", Path.home() / ".kit-ia") / "projetos.json"


@contextmanager
def bloquear_projetos():
    caminho = arquivo_projetos().with_suffix(".lock")
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        # O arquivo permanece: apagá-lo permitiria bloquear arquivos diferentes para o
        # mesmo registro. O SO libera o bloqueio mesmo se o processo for interrompido.
        with caminho.open("a+b") as trava:
            if os.name == "nt":
                msvcrt.locking(trava.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(trava.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    msvcrt.locking(trava.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(trava.fileno(), fcntl.LOCK_UN)
    except OSError as erro:
        raise ErroKit(f"não consegui acessar o bloqueio do registro {caminho}: {erro}") from erro


def carregar_projetos() -> dict:
    caminho = arquivo_projetos()
    try:
        if not caminho.exists():
            return {}
        projetos = ler_json(caminho)
        if not isinstance(projetos, dict):
            raise ErroKit(f"{caminho}: o registro precisa ser um mapa de caminhos absolutos")
        for pasta, dados in projetos.items():
            if (not Path(pasta).is_absolute() or not isinstance(dados, dict)
                    or not isinstance(dados.get("agentes"), list) or not dados["agentes"]
                    or not all(isinstance(nome, str) for nome in dados["agentes"])
                    or (dados.get("skills") is not None and (
                        not isinstance(dados["skills"], list)
                        or not all(isinstance(nome, str) for nome in dados["skills"])))
                    or not isinstance(dados.get("sem_mcp", False), bool)):
                raise ErroKit(f"{caminho}: entrada inválida para {pasta}")
        return projetos
    except (OSError, UnicodeError) as erro:
        raise ErroKit(f"não consegui ler {caminho}: {erro}") from erro


def salvar_projetos(projetos: dict):
    caminho = arquivo_projetos()
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        # Trocar o arquivo completo evita deixar JSON truncado se a gravação falhar.
        temporario = caminho.with_suffix(".tmp")
        temporario.write_text(json.dumps(projetos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporario.replace(caminho)
    except (OSError, UnicodeError) as erro:
        raise ErroKit(f"não consegui gravar {caminho}: {erro}") from erro


def registrar_projeto(base: Path, agentes: list[str], skills: list[str] | None, sem_mcp: bool):
    # Bloquear só a escrita ainda perderia entradas lidas por instalações concorrentes.
    with bloquear_projetos():
        projetos = carregar_projetos()
        projetos[str(base)] = {"agentes": agentes, "versao": VERSAO,
                               "data": datetime.now(timezone.utc).isoformat(),
                               "skills": skills, "sem_mcp": sem_mcp}
        salvar_projetos(projetos)


def pendencias_projeto(base: Path, registro: dict | None) -> tuple[str, list[str]]:
    pasta_kit = base / PASTA_NO_PROJETO
    arquivo_versao = pasta_kit / "VERSAO"
    versao = arquivo_versao.read_text(encoding="utf-8").strip() if arquivo_versao.is_file() else "ausente"
    pendencias = []
    if versao != VERSAO:
        pendencias.append(f"versão instalada {versao}; atual {VERSAO}")

    agentes = selecionar_agentes(registro["agentes"] if registro else None)
    skills = selecionar_skills(registro.get("skills") if registro else None)
    copias = {pasta_kit / nome: RAIZ / nome for nome in PASTAS_COPIADAS}
    destinos = {base / cfg["skills"] for cfg in agentes.values() if cfg.get("skills")}
    copias.update((destino / skill.name, skill) for destino in destinos for skill in skills)
    # Uma seleção menor não apaga cópias anteriores; o marcador continua atribuindo-as
    # ao kit, inclusive nos destinos dos agentes que deixaram de ser selecionados.
    todos_destinos = {base / cfg["skills"] for cfg in carregar_agentes().values() if cfg.get("skills")}
    for destino in sorted(todos_destinos):
        if destino.is_dir():
            for copia in destino.iterdir():
                if copia.is_dir() and (copia / MARCADOR).is_file():
                    copias.setdefault(copia, PASTA_SKILLS / copia.name)
    for copia, fonte in sorted(copias.items()):
        relativo = copia.relative_to(base).as_posix()
        if not copia.exists():
            # Sem registro, só é possível atribuir ao kit pastas com o marcador.
            if registro or copia.parent == pasta_kit:
                pendencias.append(f"cópia ausente: {relativo}")
        elif (copia / MARCADOR).is_file():
            if not fonte.is_dir() or not pastas_iguais(fonte, copia):
                pendencias.append(f"cópia desatualizada: {relativo}")
        elif registro or copia.parent == pasta_kit:
            pendencias.append(f"pasta do usuário, mantida: {relativo}")

    try:
        modelo = ler_projeto(PASTA_TEMPLATES / "projeto.yaml")
        configuracao = ler_projeto(base)
        for chave, valor in modelo.items():
            if chave not in configuracao:
                pendencias.append(f"chave ausente no projeto.yaml: {chave}")
            elif isinstance(valor, dict):
                existente = configuracao[chave]
                for subchave in valor:
                    if not isinstance(existente, dict) or subchave not in existente:
                        pendencias.append(f"chave ausente no projeto.yaml: {chave}.{subchave}")
    except ErroKit as erro:
        pendencias.append(str(erro))

    agents_md = base / "AGENTS.md"
    if not agents_md.is_file() or REFERENCIA_NUCLEO not in agents_md.read_text(encoding="utf-8"):
        pendencias.append(f"AGENTS.md não aponta o processo ({REFERENCIA_NUCLEO})")
    claude_md = base / "CLAUDE.md"
    if claude_md.exists() or (registro and "claude" in agentes):
        if not claude_md.is_file() or "@AGENTS.md" not in claude_md.read_text(encoding="utf-8"):
            pendencias.append("CLAUDE.md não importa o AGENTS.md (@AGENTS.md)")
    return versao, pendencias


def cmd_status(args) -> int:
    projetos = carregar_projetos()
    caminhos = [str(Path(args.projeto).expanduser().resolve())] if args.projeto else sorted(projetos)
    if not caminhos:
        print("Nenhum projeto registrado.")
    for caminho in caminhos:
        base = Path(caminho)
        if not base.is_dir():
            print(f"{base}: aviso: pasta inexistente")
            continue
        try:
            versao, pendencias = pendencias_projeto(base, projetos.get(caminho))
        except (OSError, UnicodeError) as erro:
            raise ErroKit(f"não consegui inspecionar {base}: {erro}") from erro
        estado = f"{len(pendencias)} pendência(s)" if pendencias else "em dia"
        print(f"{base}: instalada {versao}; atual {VERSAO}; {estado}")
        if args.detalhes:
            for pendencia in pendencias:
                print(f"  - {pendencia}")
    return 0


def cmd_atualizar(args) -> int:
    projetos = carregar_projetos()
    caminhos = [str(Path(args.projeto).expanduser().resolve())] if args.projeto else sorted(projetos)
    if args.projeto and caminhos[0] not in projetos:
        raise ErroKit(f"projeto não registrado: {caminhos[0]}; use install primeiro")
    resumos = []
    falhas = False
    for caminho in caminhos:
        if not Path(caminho).is_dir():
            acao = "seria removida do registro" if args.simular else "removida do registro"
            aviso = f"pasta inexistente; {acao}"
            if not args.simular:
                with bloquear_projetos():
                    atuais = carregar_projetos()
                    # A lista do lote pode anteceder instalações feitas por outro processo.
                    if not Path(caminho).is_dir():
                        atuais.pop(caminho, None)
                        salvar_projetos(atuais)
                    else:
                        aviso = "pasta reapareceu; mantida no registro"
            resumos.append(f"{caminho}: aviso: {aviso}")
            continue
        registro = projetos[caminho]
        opcoes = argparse.Namespace(destino=caminho, global_=False, agentes=",".join(registro["agentes"]),
                                    skills=",".join(registro["skills"]) if registro.get("skills") else None,
                                    sem_mcp=registro.get("sem_mcp", False), mcp_global=False,
                                    forcar=False, simular=args.simular)
        try:
            ex = instalar(opcoes)
            resumos.append(f"{caminho}: {ex.mudancas} mudança(s), {ex.avisos} aviso(s)")
        except (ErroKit, OSError, UnicodeError) as erro:
            resumos.append(f"{caminho}: erro: {erro}")
            falhas = True
    print("\nResumo da atualização" + (" [simulação]:" if args.simular else ":"))
    print("\n".join(resumos) if resumos else "Nenhum projeto registrado.")
    return 1 if falhas else 0


# =============================================================== listar / validar / nova-skill

def cmd_listar(args) -> int:
    print("Skills (pasta skills/):")
    for pasta in pastas_de_skills():
        print(f"  {pasta.name}\n      {descricao_da_skill(pasta)}")
    print("\nAgentes (config/agentes.json):")
    for nome, cfg in carregar_agentes().items():
        print(f"  {nome:<10} {cfg.get('descricao', '')}")
    print("\nServidores MCP (config/mcp.json):")
    for nome, s in carregar_servidores().items():
        print(f"  {nome:<10} {s.get('descricao', '')}")
    return 0


PADRAO_LINK = re.compile(r"\]\(([^)\s]+)\)")
PADRAO_BLOCO_CODIGO = re.compile(r"```.*?```", re.DOTALL)


def links_quebrados(raiz: Path) -> list[str]:
    """Links relativos em Markdown que apontam para arquivo inexistente.

    A documentação do processo se referencia o tempo todo; um link quebrado manda o agente
    procurar um arquivo que não existe (e gastar tokens nisso). Blocos de código são ignorados.
    """
    problemas = []
    arquivos = sorted({a for padrao in ARQUIVOS_COM_LINKS for a in raiz.glob(padrao) if a.is_file()})
    for arquivo in arquivos:
        texto = PADRAO_BLOCO_CODIGO.sub("", arquivo.read_text(encoding="utf-8"))
        for alvo in PADRAO_LINK.findall(texto):
            if alvo.startswith(("http://", "https://", "mailto:", "#")):
                continue
            caminho = alvo.split("#", 1)[0]
            if caminho and not (arquivo.parent / caminho).exists():
                problemas.append(f"{arquivo.relative_to(raiz).as_posix()}: link quebrado -> {alvo}")
    return problemas


def cmd_validar(args) -> int:
    print("Skills:")
    pastas = pastas_de_skills()
    total = 0
    for pasta in pastas:
        problemas = problemas_da_skill(pasta)
        total += len(problemas)
        print(f"  {'ok' if not problemas else 'ERRO'}  {pasta.name}")
        for problema in problemas:
            print(f"        - {problema}")

    print("\nLinks da documentação:")
    quebrados = links_quebrados(RAIZ)
    total += len(quebrados)
    for problema in quebrados:
        print(f"  ERRO  {problema}")
    if not quebrados:
        print("  ok")

    carregar_servidores()  # também valida config/mcp.json
    print(f"\n{len(pastas)} skill(s), {total} problema(s).")
    return 1 if total else 0


def cmd_nova_skill(args) -> int:
    nome = args.nome
    if len(nome) > MAX_NOME or not PADRAO_NOME.match(nome):
        raise ErroKit("nome inválido: use minúsculas, números e hífen (ex.: gerar-changelog)")
    pasta = PASTA_SKILLS / nome
    if pasta.exists():
        raise ErroKit(f"a skill {nome} já existe em {pasta}")
    descricao = args.descricao or "TODO: o que a skill faz. Use quando <situações e frases que devem ativá-la>."
    texto = (
        (PASTA_TEMPLATES / "SKILL.md").read_text(encoding="utf-8")
        .replace("{{nome}}", nome)
        .replace("{{descricao}}", descricao)
        .replace("{{titulo}}", nome.replace("-", " ").capitalize())
    )
    pasta.mkdir(parents=True)
    (pasta / "SKILL.md").write_text(texto, encoding="utf-8", newline="\n")
    print(f"Criada {pasta / 'SKILL.md'}. Preencha as seções e rode `python kit.py validate`.")
    return 0


# =============================================================== executar (qualquer modelo)

INSTRUCAO_SEM_FERRAMENTAS = """Você está executando a skill abaixo FORA de um agente de código:
não há ferramentas, você não pode rodar comandos nem abrir arquivos.
Trabalhe só com a entrada recebida. Quando a skill pedir um passo que exige ferramenta,
diga o que deveria ser feito em vez de inventar o resultado.

=== SKILL: {nome} ===
{corpo}"""


def carregar_env(caminho: Path) -> dict:
    """Lê KEY=VALOR de um .env simples (sem dependência do python-dotenv)."""
    valores = {}
    if caminho.is_file():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, _, valor = linha.partition("=")
                valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def config_modelo(args) -> dict:
    """Ordem de prioridade: argumento > variável de ambiente > .env > padrão (Ollama local)."""
    arquivo = carregar_env(ARQUIVO_ENV)

    def valor(nome: str, padrao: str = "") -> str:
        return os.environ.get(nome) or arquivo.get(nome) or padrao

    protocolo = args.protocolo or valor("KIT_IA_PROTOCOLO", "openai")
    if protocolo not in ("openai", "anthropic"):
        raise ErroKit("KIT_IA_PROTOCOLO deve ser 'openai' (Ollama, OpenRouter, OpenAI, Gemini...) ou 'anthropic'")
    return {
        "protocolo": protocolo,
        "url": (args.url or valor("KIT_IA_URL", "http://localhost:11434/v1")).rstrip("/"),
        "modelo": args.modelo or valor("KIT_IA_MODELO", "qwen2.5:3b"),
        "chave": valor("KIT_IA_CHAVE"),
        "timeout": float(valor("KIT_IA_TIMEOUT", "180")),
    }


def post_json(url: str, corpo: dict, cabecalhos: dict, timeout: float) -> dict:
    requisicao = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json", **cabecalhos},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", errors="replace")[:800]
        raise ErroKit(f"o provedor respondeu HTTP {erro.code}: {detalhe}") from erro
    except urllib.error.URLError as erro:
        raise ErroKit(
            f"não consegui conectar em {url} ({erro.reason}). "
            "Se for o Ollama: ele está rodando (`ollama serve`) e o modelo foi baixado (`ollama pull <modelo>`)?"
        ) from erro


def chamar_modelo(cfg: dict, sistema: str, entrada: str, task=None) -> str:
    """Um adaptador por protocolo. Todo provedor cabe em um destes dois formatos."""
    inicio, relogio = datetime.now(timezone.utc), time.monotonic()

    def registrar(resposta):
        try:
            custo.registrar_uso(cfg, resposta, inicio, time.monotonic() - relogio, task)
        except ValueError:
            print("aviso: telemetria de uso inválida; registro não gravado", file=sys.stderr)
        except (OSError, TypeError):
            print("aviso: não foi possível gravar o registro de uso", file=sys.stderr)

    def requisitar(*argumentos):
        try:
            resposta = post_json(*argumentos)
        except ErroKit:
            registrar({})  # Mesmo sem uso conhecido, a tentativa consumiu tempo.
            raise
        registrar(resposta)
        return resposta

    if cfg["protocolo"] == "anthropic":
        if not cfg["chave"]:
            raise ErroKit("defina KIT_IA_CHAVE com a chave da Anthropic (no .env ou no ambiente)")
        resposta = requisitar(
            f"{cfg['url']}/messages",
            {
                "model": cfg["modelo"],
                "max_tokens": 16000,
                "system": sistema,
                "messages": [{"role": "user", "content": entrada}],
            },
            {"x-api-key": cfg["chave"], "anthropic-version": "2026-10-21"},
            cfg["timeout"],
        )
        if resposta.get("stop_reason") == "refusal":
            raise ErroKit(f"o modelo recusou o pedido: {resposta.get('stop_details')}")
        # A resposta é uma lista de blocos (pode haver blocos de raciocínio): só o texto interessa.
        return "\n".join(b["text"] for b in resposta.get("content", []) if b.get("type") == "text")

    cabecalhos = {"Authorization": f"Bearer {cfg['chave']}"} if cfg["chave"] else {}
    resposta = requisitar(
        f"{cfg['url']}/chat/completions",
        {
            "model": cfg["modelo"],
            "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": entrada}],
        },
        cabecalhos,
        cfg["timeout"],
    )
    try:
        return resposta["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as erro:
        raise ErroKit(f"resposta inesperada do provedor: {json.dumps(resposta)[:500]}") from erro


def cmd_executar(args) -> int:
    pasta = PASTA_SKILLS / args.skill
    if not (pasta / "SKILL.md").is_file():
        raise ErroKit(f"skill '{args.skill}' não encontrada em {PASTA_SKILLS}")
    _, corpo = ler_frontmatter((pasta / "SKILL.md").read_text(encoding="utf-8"))

    if args.entrada:
        caminho = Path(args.entrada)
        entrada = caminho.read_text(encoding="utf-8") if caminho.is_file() else args.entrada
    elif not sys.stdin.isatty():
        entrada = sys.stdin.read()
    else:
        entrada = ""
    if not entrada.strip():
        raise ErroKit('sem entrada: passe --input "texto" ou um arquivo, ou envie por pipe (git diff | ...)')

    cfg = config_modelo(args)
    print(f"[kit] skill={args.skill} protocolo={cfg['protocolo']} modelo={cfg['modelo']} url={custo.url_publica(cfg['url'])}", file=sys.stderr)
    sistema = INSTRUCAO_SEM_FERRAMENTAS.format(nome=args.skill, corpo=corpo)
    print(chamar_modelo(cfg, sistema, entrada, args.task))
    return 0


def ler_projeto(caminho: Path) -> dict:
    if caminho.is_dir():
        caminho = caminho / PASTA_NO_PROJETO / "projeto.yaml"
    try:
        return custo.ler_yaml(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise ErroKit(f"não consegui ler projeto.yaml: {erro}") from erro


def pasta_do_projeto(caminho: str) -> Path:
    projeto = Path(caminho).resolve()
    pasta = projeto if projeto.is_dir() else projeto.parent
    return pasta.parent if pasta.name == PASTA_NO_PROJETO else pasta


def cmd_custo(args) -> int:
    if (args.projeto and args.verificar_orcamento
            and pasta_do_projeto(args.projeto) != pasta_do_projeto(args.verificar_orcamento)):
        raise ErroKit("--project e --check-budget devem indicar o mesmo projeto")
    desde = custo.data(args.desde) if args.desde else None
    if args.desde and desde is None:
        raise ErroKit("--since deve ser uma data ISO, por exemplo 2026-11-16")
    ate = custo.data(args.ate) if args.ate else None
    if args.ate and ate is None:
        raise ErroKit("--until deve ser uma data ISO, por exemplo 2026-11-17")
    if desde and ate and desde > ate:
        raise ErroKit("--since não pode ser posterior a --until")
    try:
        precos = json.loads((RAIZ / "config/precos.json").read_text(encoding="utf-8"))["precos"]
        if not isinstance(precos, dict) or any(not isinstance(valor, dict) for valor in precos.values()):
            raise ValueError("precos deve ser um mapa de modelos e tarifas")
    except (OSError, ValueError, KeyError, TypeError) as erro:
        raise ErroKit(f"config/precos.json inválido: {erro}") from erro
    registros, avisos = custo.coletar()
    if desde:
        # O filtro inclui a sessão inteira se houve atividade no período; não estima frações de uso.
        registros = [item for item in registros if (item["fim"] and item["fim"] >= desde)
                     or item.get("janela_incerta")
                     or (item["fim"] is None and item.get("medicao_incompleta"))]
    if ate:
        registros = [item for item in registros if (item["inicio"] and item["inicio"] <= ate)
                     or item.get("janela_incerta")
                     or (item["inicio"] is None and item.get("medicao_incompleta"))]
    lote = [item.strip() for item in args.lote.split(",") if item.strip()] if args.lote else []
    if lote:
        registros = [item for item in registros if item["task"] in lote
                     or (item.get("medicao_incompleta") and item["task"] == "(sem task)")]
    por = "task" if lote or args.verificar_orcamento else {
        "task": "task", "model": "modelo", "agent": "agente", "role": "papel", "day": "dia"
    }[args.por]
    estouros = []
    incompletas = []
    if args.verificar_orcamento:
        projeto = Path(args.verificar_orcamento).resolve()
        configuracao = ler_projeto(projeto)
        orcamento = configuracao.get("orcamento")
        limites = orcamento.get("por_task", {}) if isinstance(orcamento, dict) else {}
        if not isinstance(limites, dict) or any(custo.numero(limites.get(campo)) is None for campo in ("tokens", "minutos")):
            raise ErroKit("orcamento.por_task precisa de tokens e minutos numéricos não negativos")
    if args.projeto or args.verificar_orcamento:
        raiz_projeto = pasta_do_projeto(args.projeto or args.verificar_orcamento)
        raizes = custo.raizes_projeto(raiz_projeto)
        def do_projeto(item):
            if not item["pasta"]:
                return item.get("medicao_incompleta", False)
            try:
                return any(Path(item["pasta"]).resolve().is_relative_to(raiz) for raiz in raizes)
            except (OSError, ValueError):
                return False
        registros = [item for item in registros if do_projeto(item)]
    grupos = custo.agrupar(registros, por, precos)
    if args.verificar_orcamento:
        for grupo in grupos:
            for campo in ("tokens", "minutos"):
                superior = grupo[f"limite_superior_{campo}"]
                if superior > limites[campo]:
                    estouros.append(f"{grupo['task']}: {campo} {superior:.2f} > {limites[campo]}")
            if grupo["medicao_incompleta"]:
                incompletas.append(f"{grupo['task']}: medição incompleta")
            if grupo["parcial"]:
                avisos.append(f"{grupo['task']}: orçamento de tokens só verificável parcialmente")
    if args.json:
        print(json.dumps({"por": por, "grupos": grupos, "avisos": sorted(set(avisos)), "estouros": estouros,
                          "incompletas": incompletas},
                         ensure_ascii=False, indent=2))
    else:
        if lote:
            print(f"Lote: {', '.join(lote)}")
            print("| Task | Tokens estimados | Tempo (min) | Custo (USD) | Limite superior tokens | Limite superior min |")
            print("| --- | ---: | ---: | ---: | ---: | ---: |")
        else:
            print(f"{por:<24} {'Entrada':>12} {'Saída':>10} {'Cache ler':>12} {'Cache gravar':>12} {'Tokens':>12} {'Minutos':>10} {'USD':>12} {'Limite tokens':>14} {'Limite min':>12}")
        for grupo in grupos:
            valor = "—" if grupo["custo_usd"] is None else f"{grupo['custo_usd']:.6f}"
            tokens = (str(grupo["tokens"]) if grupo["tokens"] is not None else "—") + ("*" if grupo["parcial"] else "")
            superior = str(grupo["limite_superior_tokens"]) + ("*" if grupo["medicao_incompleta"] else "")
            if lote:
                print(f"| {grupo[por]} | {tokens} | {grupo['minutos']:.2f} | {valor} | {superior} | {grupo['limite_superior_minutos']:.2f} |")
            else:
                campos = [str(grupo[campo]) if grupo[campo] is not None else "—" for campo in
                          ("entrada", "saida", "cache_leitura", "cache_escrita")]
                print(f"{grupo[por]:<24} {campos[0]:>12} {campos[1]:>10} {campos[2]:>12} "
                      f"{campos[3]:>12} {tokens:>12} {grupo['minutos']:>10.2f} {valor:>12} {superior:>14} {grupo['limite_superior_minutos']:>12.2f}")
        if lote:
            fontes = custo.agrupar(registros, "agente", precos)
            if fontes:
                conhecidas = [item for item in fontes if item["custo_usd"] is not None]
                maior = max(conhecidas, key=lambda item: item["custo_usd"]) if len(conhecidas) == len(fontes) else fontes[0]
                criterio = "USD" if len(conhecidas) == len(fontes) else "tokens; preços incompletos"
                print(f"Maior fonte de gasto: {maior['agente']} ({criterio}).")
        if not grupos:
            print("Nenhum uso encontrado para os filtros.")
        for aviso in sorted(set(avisos)):
            print(f"aviso: {aviso}", file=sys.stderr)
        for estouro in estouros:
            print(f"ORÇAMENTO EXCEDIDO: {estouro}")
        for incompleta in incompletas:
            print(f"ORÇAMENTO NÃO VERIFICÁVEL: {incompleta}")
    return 1 if estouros or incompletas else 0


# =============================================================== CLI

def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"dev-amys-ai {VERSAO}")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("list", help="lista skills, agentes e servidores MCP").set_defaults(func=cmd_listar)
    sub.add_parser("validate", help="confere as skills contra o padrão Agent Skills").set_defaults(func=cmd_validar)

    p = sub.add_parser("install", help="instala skills, processo, padrões, AGENTS.md e MCP em um projeto (ou --global)")
    p.add_argument("destino", nargs="?", help="pasta do projeto")
    p.add_argument("--global", dest="global_", action="store_true", help="instala as skills para o usuário (todos os projetos)")
    p.add_argument("--agents", dest="agentes", help="lista separada por vírgula (padrão: todos de config/agentes.json)")
    p.add_argument("--skills", help="lista separada por vírgula (padrão: todas)")
    p.add_argument("--no-mcp", dest="sem_mcp", action="store_true", help="omite arquivos e comandos de MCP")
    p.add_argument("--mcp-global", action="store_true", help="oferece executar os comandos globais de MCP, após confirmação")
    p.add_argument("--force", dest="forcar", action="store_true", help="substitui skills e servidores que não são do kit")
    p.add_argument("--dry-run", dest="simular", action="store_true", help="mostra o que faria, sem escrever nada")
    p.set_defaults(func=cmd_instalar)

    p = sub.add_parser("uninstall", help="remove apenas arquivos e entradas gerenciados pelo kit")
    p.add_argument("destino", nargs="?", help="pasta do projeto")
    p.add_argument("--global", dest="global_", action="store_true", help="remove só skills globais com marcador")
    p.add_argument("--agents", dest="agentes", help="lista separada por vírgula (padrão: todos)")
    p.add_argument("--dry-run", dest="simular", action="store_true", help="mostra remoções sem alterar nem perguntar")
    p.add_argument("--yes", action="store_true", help="confirma a remoção local; MCP global tem confirmação própria")
    p.add_argument("--mcp-global", action="store_true", help="oferece remover MCP global após confirmação")
    p.set_defaults(func=cmd_desinstalar)

    p = sub.add_parser("status", help="mostra versões e pendências dos projetos instalados")
    p.add_argument("projeto", nargs="?", help="pasta do projeto (padrão: todos os registrados)")
    p.add_argument("--details", dest="detalhes", action="store_true", help="lista cópias e chaves pendentes")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("update", help="reinstala o kit nos projetos registrados, preservando arquivos do usuário")
    p.add_argument("projeto", nargs="?", help="pasta registrada (padrão: todas)")
    p.add_argument("--dry-run", dest="simular", action="store_true", help="mostra o que faria, sem escrever nada")
    p.set_defaults(func=cmd_atualizar)

    p = sub.add_parser("new-skill", help="cria uma skill nova a partir do modelo")
    p.add_argument("nome", help="nome em kebab-case (ex.: gerar-changelog)")
    p.add_argument("--description", dest="descricao", help="o que faz e quando usar")
    p.set_defaults(func=cmd_nova_skill)

    p = sub.add_parser("run", help="executa uma skill em qualquer modelo (sem ferramentas)")
    p.add_argument("skill")
    p.add_argument("--input", dest="entrada", help="texto ou caminho de arquivo (ou use pipe)")
    p.add_argument("--protocol", dest="protocolo", choices=["openai", "anthropic"])
    p.add_argument("--url", help="base da API (ex.: http://localhost:11434/v1)")
    p.add_argument("--model", dest="modelo")
    p.add_argument("--task", help="ID da task; sem isso, detecta pela branch ou pasta")
    p.set_defaults(func=cmd_executar)

    p = sub.add_parser("cost", help="mede uso local por task, modelo, agente e papel, sem chamar modelos")
    p.add_argument("--since", dest="desde", help="inclui sessões com atividade desde a data ISO")
    p.add_argument("--until", dest="ate", help="inclui sessões iniciadas até a data ISO")
    p.add_argument("--project", dest="projeto", help="filtra pelo projeto e suas worktrees")
    p.add_argument("--by", dest="por", choices=["task", "model", "agent", "role", "day"], default="task")
    p.add_argument("--batch", dest="lote", help="IDs separados por vírgula; produz tabela Markdown")
    p.add_argument("--check-budget", dest="verificar_orcamento", metavar="PROJETO", help="confere orcamento.por_task pelo limite superior; medição incompleta falha")
    p.add_argument("--json", action="store_true", help="saída estruturada para programas")
    p.set_defaults(func=cmd_custo)
    return parser


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(fluxo, "reconfigure"):  # acentos no console do Windows
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    args = montar_parser().parse_args(argv)
    try:
        return args.func(args)
    except ErroKit as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
