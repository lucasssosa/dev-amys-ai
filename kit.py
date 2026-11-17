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
    python kit.py listar
    python kit.py validar
    python kit.py instalar ../meu-projeto --simular
    python kit.py instalar --global
    python kit.py nova-skill gerar-changelog --descricao "Gera ... Use quando ..."
    git diff | python kit.py executar revisar
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import custo

VERSAO = "0.2.0"

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

# Arquivos Markdown cujos links relativos o `validar` confere.
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
        return "(inválida: rode `python kit.py validar`)"


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


# =============================================================== execução (com --simular)

class Execucao:
    """Faz (ou só mostra, com --simular) cada mudança no disco, e conta o que mudou."""

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

        Pasta sem o MARCADOR é do usuário: só é trocada com --forcar.
        Pasta com o MARCADOR é cópia do kit: é atualizada sempre (edições à mão se perdem,
        e é de propósito: regra própria do projeto vai no AGENTS.md ou no projeto.yaml).
        """
        if destino.exists():
            if not (destino / MARCADOR).exists() and not forcar:
                self.aviso(f"{destino} já existe e não foi instalada pelo kit: mantida (use --forcar para trocar)")
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
                ex.aviso(f"{caminho}: já tem o servidor '{nome}' com outra configuração; mantido (use --forcar)")
            continue
        container[nome] = converter_servidor(formato, servidor)
    if formato == "gemini":
        # O Gemini CLI lê GEMINI.md por padrão; isto faz ele ler também o AGENTS.md.
        dados.setdefault("context", {}).setdefault("fileName", ["AGENTS.md", "GEMINI.md"])
    ex.escrever(caminho, json.dumps(dados, indent=2, ensure_ascii=False) + "\n")


def instalar_mcp_global(ex: Execucao, configuracoes: list[dict], servidores: dict, executar: bool):
    print("\nMCP global (rode uma vez):")
    pendentes = []
    for mcp in configuracoes:
        formato = mcp["formato"]
        if formato == "comando-codex":
            for nome, servidor in servidores.items():
                if servidor.get("cabecalhos"):
                    ex.aviso(f"Codex: servidor '{nome}' tem cabeçalhos; configure à mão")
        for comando in comandos_mcp_global(formato, servidores):
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


def cmd_instalar(args) -> int:
    agentes = selecionar_agentes(lista_csv(args.agentes))
    skills = selecionar_skills(lista_csv(args.skills))
    ex = Execucao(args.simular)
    prefixo = "[simulação] " if args.simular else ""

    if args.global_:
        print(f"{prefixo}Instalando {len(skills)} skill(s) no nível do usuário (vale para todos os projetos):")
        destinos = {Path(cfg["skills_global"]).expanduser() for cfg in agentes.values() if cfg.get("skills_global")}
    else:
        if not args.destino:
            raise ErroKit("informe a pasta do projeto (ex.: python kit.py instalar ../meu-projeto) ou use --global")
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

    verbo = "seriam feitas" if args.simular else "feitas"
    print(f"\n{ex.mudancas} mudança(s) {verbo}, {ex.avisos} aviso(s).")
    return 0


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
    print(f"Criada {pasta / 'SKILL.md'}. Preencha as seções e rode `python kit.py validar`.")
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
        except (OSError, ValueError, TypeError):
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
        raise ErroKit('sem entrada: passe --entrada "texto" ou um arquivo, ou envie por pipe (git diff | ...)')

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


def cmd_custo(args) -> int:
    desde = custo.data(args.desde) if args.desde else None
    if args.desde and desde is None:
        raise ErroKit("--desde deve ser uma data ISO, por exemplo 2026-11-16")
    try:
        precos = json.loads((RAIZ / "config/precos.json").read_text(encoding="utf-8"))["precos"]
        if not isinstance(precos, dict) or any(not isinstance(valor, dict) for valor in precos.values()):
            raise ValueError("precos deve ser um mapa de modelos e tarifas")
    except (OSError, ValueError, KeyError, TypeError) as erro:
        raise ErroKit(f"config/precos.json inválido: {erro}") from erro
    registros, avisos = custo.coletar()
    if desde:
        # O filtro inclui a sessão inteira se houve atividade no período; não estima frações de uso.
        registros = [item for item in registros if item["fim"] and item["fim"] >= desde]
    lote = [item.strip() for item in args.lote.split(",") if item.strip()] if args.lote else []
    if lote:
        registros = [item for item in registros if item["task"] in lote]
    por = "task" if lote or args.verificar_orcamento else args.por
    estouros = []
    if args.verificar_orcamento:
        projeto = Path(args.verificar_orcamento).resolve()
        configuracao = ler_projeto(projeto)
        orcamento = configuracao.get("orcamento")
        limites = orcamento.get("por_task", {}) if isinstance(orcamento, dict) else {}
        if not isinstance(limites, dict) or any(custo.numero(limites.get(campo)) is None for campo in ("tokens", "minutos")):
            raise ErroKit("orcamento.por_task precisa de tokens e minutos numéricos não negativos")
        raiz_projeto = projeto if projeto.is_dir() else projeto.parent
        if raiz_projeto.name == PASTA_NO_PROJETO:
            raiz_projeto = raiz_projeto.parent
        def do_projeto(item):
            try:
                return Path(item["pasta"]).resolve().is_relative_to(raiz_projeto)
            except (OSError, ValueError):
                return False
        registros = [item for item in registros if do_projeto(item)]
    grupos = custo.agrupar(registros, por, precos)
    if args.verificar_orcamento:
        for grupo in grupos:
            for campo in ("tokens", "minutos"):
                if grupo[campo] is not None and grupo[campo] > limites[campo]:
                    estouros.append(f"{grupo['task']}: {campo} {grupo[campo]:.2f} > {limites[campo]}")
            if grupo["parcial"]:
                avisos.append(f"{grupo['task']}: orçamento de tokens só verificável parcialmente")
    if args.json:
        print(json.dumps({"por": por, "grupos": grupos, "avisos": sorted(set(avisos)), "estouros": estouros},
                         ensure_ascii=False, indent=2))
    else:
        if lote:
            print(f"Lote: {', '.join(lote)}")
            print("| Task | Tokens | Tempo (min) | Custo (USD) |")
            print("| --- | ---: | ---: | ---: |")
        else:
            print(f"{por:<24} {'Entrada':>12} {'Saída':>10} {'Cache ler':>12} {'Cache gravar':>12} {'Tokens':>12} {'Minutos':>10} {'USD':>12}")
        for grupo in grupos:
            valor = "—" if grupo["custo_usd"] is None else f"{grupo['custo_usd']:.6f}"
            tokens = (str(grupo["tokens"]) if grupo["tokens"] is not None else "—") + ("*" if grupo["parcial"] else "")
            if lote:
                print(f"| {grupo[por]} | {tokens} | {grupo['minutos']:.2f} | {valor} |")
            else:
                campos = [str(grupo[campo]) if grupo[campo] is not None else "—" for campo in
                          ("entrada", "saida", "cache_leitura", "cache_escrita")]
                print(f"{grupo[por]:<24} {campos[0]:>12} {campos[1]:>10} {campos[2]:>12} "
                      f"{campos[3]:>12} {tokens:>12} {grupo['minutos']:>10.2f} {valor:>12}")
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
    return 1 if estouros else 0


# =============================================================== CLI

def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--versao", action="version", version=f"dev-amys-ai {VERSAO}")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("listar", help="lista skills, agentes e servidores MCP").set_defaults(func=cmd_listar)
    sub.add_parser("validar", help="confere as skills contra o padrão Agent Skills").set_defaults(func=cmd_validar)

    p = sub.add_parser("instalar", help="instala skills, processo, padrões, AGENTS.md e MCP em um projeto (ou --global)")
    p.add_argument("destino", nargs="?", help="pasta do projeto")
    p.add_argument("--global", dest="global_", action="store_true", help="instala as skills para o usuário (todos os projetos)")
    p.add_argument("--agentes", help="lista separada por vírgula (padrão: todos de config/agentes.json)")
    p.add_argument("--skills", help="lista separada por vírgula (padrão: todas)")
    p.add_argument("--sem-mcp", action="store_true", help="omite arquivos e comandos de MCP")
    p.add_argument("--mcp-global", action="store_true", help="oferece executar os comandos globais de MCP, após confirmação")
    p.add_argument("--forcar", action="store_true", help="substitui skills e servidores que não são do kit")
    p.add_argument("--simular", action="store_true", help="mostra o que faria, sem escrever nada")
    p.set_defaults(func=cmd_instalar)

    p = sub.add_parser("nova-skill", help="cria uma skill nova a partir do modelo")
    p.add_argument("nome", help="nome em kebab-case (ex.: gerar-changelog)")
    p.add_argument("--descricao", help="o que faz e quando usar")
    p.set_defaults(func=cmd_nova_skill)

    p = sub.add_parser("executar", help="executa uma skill em qualquer modelo (sem ferramentas)")
    p.add_argument("skill")
    p.add_argument("--entrada", help="texto ou caminho de arquivo (ou use pipe)")
    p.add_argument("--protocolo", choices=["openai", "anthropic"])
    p.add_argument("--url", help="base da API (ex.: http://localhost:11434/v1)")
    p.add_argument("--modelo")
    p.add_argument("--task", help="ID da task; sem isso, detecta pela branch ou pasta")
    p.set_defaults(func=cmd_executar)

    p = sub.add_parser("custo", help="mede uso local por task, modelo, agente e papel, sem chamar modelos")
    p.add_argument("--desde", help="inclui sessões com atividade desde a data ISO")
    p.add_argument("--por", choices=["task", "modelo", "agente", "papel"], default="task")
    p.add_argument("--lote", help="IDs separados por vírgula; produz tabela Markdown")
    p.add_argument("--verificar-orcamento", metavar="PROJETO", help="confere orcamento.por_task do projeto")
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
