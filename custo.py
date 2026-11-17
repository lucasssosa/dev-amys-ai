"""Métricas locais, sem chamadas a modelos e sem persistir conteúdo de conversas."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit


def pasta_env(nome: str, padrao: Path) -> Path:
    return Path(os.environ.get(nome) or padrao).expanduser().resolve()


def detectar_task(branch: str = "", pasta: str = "") -> str:
    achado = re.search(r"BL-[A-Z0-9]+-[0-9]+", branch + " " + pasta)
    return achado.group() if achado else "(sem task)"


def branch_atual() -> str:
    try:
        return subprocess.run(["git", "branch", "--show-current"], capture_output=True,
                              text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def data(valor) -> datetime | None:
    try:
        instante = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return instante.replace(tzinfo=timezone.utc) if instante.tzinfo is None else instante
    except (ValueError, TypeError):
        return None


def numero(valor):
    return valor if isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor) and valor >= 0 else None


def uso_resposta(resposta: dict, protocolo: str) -> dict:
    uso = resposta.get("usage") or {}
    if not isinstance(uso, dict):
        uso = {}
    if protocolo == "anthropic":
        entrada, saida = uso.get("input_tokens"), uso.get("output_tokens")
        leitura, escrita = uso.get("cache_read_input_tokens", 0), uso.get("cache_creation_input_tokens", 0)
        if numero(entrada) is not None:
            entrada += (numero(leitura) or 0) + (numero(escrita) or 0)
    else:
        entrada = uso.get("prompt_tokens", resposta.get("prompt_eval_count"))
        saida = uso.get("completion_tokens", resposta.get("eval_count"))
        detalhes = uso.get("prompt_tokens_details")
        if detalhes is not None and not isinstance(detalhes, dict):
            raise ValueError("telemetria inválida: prompt_tokens_details precisa ser um mapa")
        leitura = (detalhes or {}).get("cached_tokens", 0)
        escrita = 0
    return {"entrada": numero(entrada), "saida": numero(saida),
            "cache_leitura": numero(leitura), "cache_escrita": numero(escrita),
            "custo_usd": numero(uso.get("cost"))}


def url_publica(url: str) -> str:
    partes = urlsplit(url)
    # Credenciais na autoridade ou na query nunca pertencem à telemetria.
    return urlunsplit((partes.scheme, partes.netloc.rsplit("@", 1)[-1], partes.path, "", ""))


def registrar_uso(cfg: dict, resposta: dict, inicio: datetime, duracao: float, task=None):
    pasta = str(Path.cwd())
    registro = {"data": inicio.isoformat(), "protocolo": cfg["protocolo"],
                "url": url_publica(cfg["url"]), "modelo": cfg["modelo"],
                "duracao_segundos": duracao, "pasta": pasta,
                "task": task or detectar_task(branch_atual(), pasta), **uso_resposta(resposta, cfg["protocolo"])}
    destino = pasta_env("KIT_IA_HOME", Path.home() / ".kit-ia") / "uso.jsonl"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")


def linhas_json(arquivo: Path, avisos: list):
    try:
        with arquivo.open(encoding="utf-8") as fluxo:
            for linha in fluxo:
                try:
                    registro = json.loads(linha)
                    if isinstance(registro, dict):
                        yield registro
                except ValueError:
                    avisos.append(f"{arquivo.name}: linha JSON inválida ignorada")
    except (OSError, UnicodeError):
        avisos.append(f"{arquivo.name}: leitura indisponível")


def registro(agente, modelo, papel, pasta, branch, inicio, fim, uso, **extras):
    return {"agente": agente, "modelo": modelo or "(desconhecido)", "papel": papel,
            "pasta": pasta, "task": detectar_task(branch, pasta), "inicio": inicio,
            "fim": fim, "entrada": uso.get("entrada"), "saida": uso.get("saida"),
            "cache_leitura": uso.get("cache_leitura", 0), "cache_escrita": uso.get("cache_escrita", 0),
            "custo_usd": uso.get("custo_usd"), **extras}


def ler_claude(pasta: Path, avisos: list) -> list:
    registros, vistos = [], set()
    for arquivo in sorted(pasta.rglob("*.jsonl")):
        grupos = {}
        primeira = ultima = None
        atual, anterior, pendentes = None, None, 0
        for linha in linhas_json(arquivo, avisos):
            # Distribuir os intervalos preserva a duração da sessão sem duplicá-la por modelo.
            instante = data(linha.get("timestamp"))
            if instante:
                if primeira and instante < primeira:
                    adiantamento = (primeira - instante).total_seconds() / 60
                    if grupos:
                        next(iter(grupos.values()))["minutos"] += adiantamento
                    else:
                        pendentes += adiantamento
                primeira = min(primeira or instante, instante)
                ultima = max(ultima or instante, instante)
                intervalo = max(0, (instante - anterior).total_seconds() / 60) if anterior else 0
                if atual is None:
                    pendentes += intervalo
                else:
                    grupos[atual]["minutos"] += intervalo
                anterior = max(anterior or instante, instante)
            mensagem = linha.get("message") or {}
            if not isinstance(mensagem, dict) or not mensagem.get("usage"):
                continue
            identificador = linha.get("requestId") or mensagem.get("id")
            if identificador and identificador in vistos:
                continue
            if identificador:
                vistos.add(identificador)
            uso = mensagem["usage"]
            papel = "subagente" if linha.get("isSidechain") or "subagents" in arquivo.parts else "principal"
            local, branch = linha.get("cwd", ""), linha.get("gitBranch", "")
            chave = (mensagem.get("model"), papel, local, branch)
            if chave not in grupos:
                grupos[chave] = registro("claude", chave[0], papel, local, branch, None, None,
                                        {"entrada": 0, "saida": 0}, minutos=0)
            grupo = grupos[chave]
            atual = chave
            grupo["minutos"] += pendentes
            pendentes = 0
            for destino, origem in (("entrada", "input_tokens"), ("saida", "output_tokens"),
                                    ("cache_leitura", "cache_read_input_tokens"),
                                    ("cache_escrita", "cache_creation_input_tokens")):
                valor = numero(uso.get(origem, 0))
                grupo[destino] = None if valor is None or grupo[destino] is None else grupo[destino] + valor
            # O Claude informa entrada sem cache; normalizamos para o total de entrada.
        for grupo in grupos.values():
            if grupo["entrada"] is not None:
                grupo["entrada"] += (grupo["cache_leitura"] or 0) + (grupo["cache_escrita"] or 0)
            grupo["inicio"], grupo["fim"] = primeira, ultima
        registros.extend(grupos.values())
    return registros


def ler_codex(pasta: Path, avisos: list) -> list:
    registros = []
    for arquivo in sorted(pasta.rglob("*.jsonl")):
        primeira = ultima = None
        local = branch = modelo = ""
        papel, anterior, grupos = "principal", {}, {}
        atividades = []
        for linha in linhas_json(arquivo, avisos):
            instante = data(linha.get("timestamp"))
            if instante:
                primeira = min(primeira or instante, instante)
                ultima = max(ultima or instante, instante)
            carga = linha.get("payload") or {}
            if linha.get("type") == "session_meta":
                local = carga.get("cwd", local)
                modelo = carga.get("model", modelo)
                branch = (carga.get("git") or {}).get("branch", branch)
                primeira = data(carga.get("timestamp")) or primeira
                if isinstance(carga.get("source"), dict) or carga.get("agent_role"):
                    papel = "subagente"
            elif linha.get("type") == "turn_context":
                local = carga.get("cwd", local)
                modelo = carga.get("model", modelo)
            elif linha.get("type") == "event_msg" and carga.get("type") == "token_count":
                total = (carga.get("info") or {}).get("total_token_usage")
                if isinstance(total, dict) and total:
                    # O acumulado inclui os modelos anteriores; só o delta pertence ao atual.
                    deltas = {}
                    for destino, origem in (("entrada", "input_tokens"), ("saida", "output_tokens"),
                                            ("cache_leitura", "cached_input_tokens")):
                        valor = numero(total.get(origem, 0 if destino == "cache_leitura" else None))
                        previo = anterior.get(destino, 0)
                        delta = valor - previo if valor is not None and previo is not None else None
                        if delta is not None and delta < 0:
                            delta = None
                            avisos.append(f"{arquivo.name}: acumulado Codex regrediu; uso parcial")
                        deltas[destino] = delta
                        anterior[destino] = valor
                    if any(valor != 0 for valor in deltas.values()) or not grupos:
                        if modelo not in grupos:
                            grupos[modelo] = registro("codex", modelo, papel, local, branch, None, None,
                                                      {"entrada": 0, "saida": 0}, minutos=0)
                        grupo = grupos[modelo]
                        grupo["custo_confiavel"] = grupo.get("custo_confiavel", True) and all(
                            valor is not None for valor in deltas.values())
                        for campo, valor in deltas.items():
                            grupo[campo] = None if valor is None or grupo[campo] is None else grupo[campo] + valor
                        atividades.append((modelo, instante))
        # Cada intervalo vai para o modelo do próximo evento de uso; a cauda fica com o último.
        anterior_instante = primeira
        for nome, instante in atividades:
            if instante and anterior_instante:
                grupos[nome]["minutos"] += max(0, (instante - anterior_instante).total_seconds() / 60)
                anterior_instante = max(anterior_instante, instante)
        if atividades and ultima and anterior_instante:
            grupos[atividades[-1][0]]["minutos"] += max(0, (ultima - anterior_instante).total_seconds() / 60)
        for grupo in grupos.values():
            grupo["inicio"], grupo["fim"] = primeira, ultima
        registros.extend(grupos.values())
    return registros


def raizes_projeto(pasta: Path) -> list[Path]:
    """Inclui apenas worktrees registradas pelo Git do próprio projeto."""
    try:
        resultado = subprocess.run(["git", "-C", str(pasta), "worktree", "list", "--porcelain", "-z"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=5, check=False)
        if resultado.returncode:
            return [pasta]
        raizes = [Path(campo[len("worktree "):]).resolve() for campo in resultado.stdout.split("\0")
                  if campo.startswith("worktree ")]
        # Uma subpasta de outro repositório não herda as worktrees dele.
        return raizes if pasta in raizes else [pasta]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return [pasta]


def ler_antigravity(pasta: Path, avisos: list) -> list:
    arquivo = pasta / "conversation_summaries.db"
    if not arquivo.is_file():
        return []
    consulta = ("SELECT conversation_id, workspace_uris, last_user_input_time, last_modified_time "
                "FROM conversation_summaries")
    try:
        try:
            with closing(sqlite3.connect(arquivo.as_uri() + "?mode=ro", uri=True)) as banco:
                linhas = banco.execute(consulta).fetchall()
        except sqlite3.OperationalError:
            # Alguns ambientes impedem criar o índice do WAL mesmo numa conexão somente leitura.
            with closing(sqlite3.connect(arquivo.as_uri() + "?mode=ro&immutable=1", uri=True)) as banco:
                linhas = banco.execute(consulta).fetchall()
            avisos.append("Antigravity: leitura imutável; alterações ainda no WAL podem não aparecer")
    except sqlite3.Error:
        avisos.append("Antigravity: banco indisponível ou esquema não suportado")
        return []
    avisos.append("Antigravity: tokens desconhecidos; bancos de conversas usam blobs sem formato de uso verificado; "
                  "tempo parcial entre último envio e última alteração")
    def caminho(local):
        try:
            locais = json.loads(local)
            local = locais[0] if isinstance(locais, list) and locais else local
        except (ValueError, TypeError):
            pass
        if str(local).startswith("file://"):
            local = unquote(urlsplit(local).path)
            if re.match(r"^/[A-Za-z]:", local):
                local = local[1:]
        return str(local)
    return [registro("antigravity", "", "principal", caminho(local), "", data(inicio), data(fim), {})
            for _, local, inicio, fim in linhas]


def ler_kit(pasta: Path, avisos: list) -> list:
    arquivo = pasta / "uso.jsonl"
    if not arquivo.is_file():
        return []
    registros = []
    for linha in linhas_json(arquivo, avisos):
        inicio = data(linha.get("data"))
        item = registro("kit", linha.get("modelo"), "executar", linha.get("pasta", ""), "", inicio, inicio,
                        {chave: numero(linha.get(chave)) for chave in
                         ("entrada", "saida", "cache_leitura", "cache_escrita", "custo_usd")})
        item["task"] = linha.get("task") or item["task"]
        item["minutos"] = (numero(linha.get("duracao_segundos")) or 0) / 60
        registros.append(item)
    return registros


def coletar() -> tuple[list, list]:
    casa, avisos = Path.home(), []
    registros = ler_claude(pasta_env("KIT_IA_CLAUDE_DIR", casa / ".claude/projects"), avisos)
    registros += ler_codex(pasta_env("KIT_IA_CODEX_DIR", casa / ".codex/sessions"), avisos)
    registros += ler_antigravity(pasta_env("KIT_IA_ANTIGRAVITY_DIR", casa / ".gemini/antigravity"), avisos)
    registros += ler_kit(pasta_env("KIT_IA_HOME", casa / ".kit-ia"), avisos)
    return registros, sorted(set(avisos))


def calcular_custo(item: dict, precos: dict):
    if item.get("custo_usd") is not None:
        return item["custo_usd"]
    if item.get("custo_confiavel") is False:
        return None
    preco = precos.get(item["modelo"])
    if not preco or item["entrada"] is None or item["saida"] is None:
        return None
    leitura, escrita = item.get("cache_leitura") or 0, item.get("cache_escrita") or 0
    quantidades = {"entrada": max(0, item["entrada"] - leitura - escrita), "saida": item["saida"],
                   "cache_leitura": leitura, "cache_escrita": escrita}
    if any(numero(preco.get(chave)) is None for chave, valor in quantidades.items() if valor):
        return None
    return sum(valor * preco[chave] for chave, valor in quantidades.items() if valor) / 1_000_000


def agrupar(registros: list, por: str, precos: dict) -> list:
    grupos = {}
    for item in registros:
        chave = item[por]
        if chave not in grupos:
            grupos[chave] = {por: chave, "entrada": 0, "saida": 0, "cache_leitura": 0,
                             "cache_escrita": 0, "tokens": 0, "minutos": 0, "custo_usd": 0,
                             "parcial": False, "uso_conhecido": False}
        grupo = grupos[chave]
        grupo["uso_conhecido"] |= item.get("entrada") is not None or item.get("saida") is not None
        for campo in ("entrada", "saida", "cache_leitura", "cache_escrita"):
            if item.get(campo) is None:
                grupo["parcial"] = True
            grupo[campo] += item.get(campo) or 0
        grupo["tokens"] = grupo["entrada"] + grupo["saida"]
        if "minutos" in item:
            grupo["minutos"] += item["minutos"]
        elif item["inicio"] and item["fim"]:
            grupo["minutos"] += max(0, (item["fim"] - item["inicio"]).total_seconds() / 60)
        valor = calcular_custo(item, precos)
        grupo["custo_usd"] = None if valor is None or grupo["custo_usd"] is None else grupo["custo_usd"] + valor
    for grupo in grupos.values():
        if not grupo.pop("uso_conhecido"):
            for campo in ("tokens", "entrada", "saida", "cache_leitura", "cache_escrita"):
                grupo[campo] = None
    return sorted(grupos.values(), key=lambda item: item["tokens"] or 0, reverse=True)


def separar(texto: str, delimitador: str) -> list[str]:
    """Separa apenas fora de aspas e coleções, preservando comentários dentro de strings."""
    partes, inicio, pilha, aspas, escape = [], 0, [], "", False
    inicio_escalar = True
    for indice, caractere in enumerate(texto):
        if aspas:
            if escape:
                escape = False
            elif caractere == "\\" and aspas == '"':
                escape = True
            elif caractere == aspas:
                if aspas == "'" and indice + 1 < len(texto) and texto[indice + 1] == "'":
                    escape = True  # Duas aspas simples representam um apóstrofo no YAML.
                else:
                    aspas = ""
        elif caractere in "\"'" and inicio_escalar:
            aspas = caractere
            inicio_escalar = False
        elif caractere in "[{":
            pilha.append(caractere)
            inicio_escalar = True
        elif caractere in "]}":
            if not pilha or (pilha.pop(), caractere) not in (("[", "]"), ("{", "}")):
                raise ValueError("coleção mal fechada")
            inicio_escalar = False
        elif caractere == delimitador and not pilha:
            if delimitador == "#" and indice and not texto[indice - 1].isspace():
                continue
            partes.append(texto[inicio:indice].strip())
            inicio = indice + 1
            if delimitador == "#":
                return partes
            inicio_escalar = True
        elif caractere in ":,":
            inicio_escalar = True
        elif not caractere.isspace():
            # O hífen de uma lista não faz parte do escalar que vem depois.
            if not (inicio_escalar and caractere == "-" and texto[indice + 1:indice + 2].isspace()):
                inicio_escalar = False
    if aspas or pilha:
        raise ValueError("aspas ou coleção sem fechamento")
    return partes + [texto[inicio:].strip()]


def escalar_yaml(texto: str):
    texto = texto.strip()
    if not texto:
        raise ValueError("valor vazio")
    if texto.startswith("{{") and texto.endswith("}}"):
        return texto  # Marcador do template distribuído com o kit.
    if texto[0] == '"':
        valor = json.loads(texto)
        if not isinstance(valor, str):
            raise ValueError("string inválida")
        return valor
    if texto[0] == "'":
        if not re.fullmatch(r"'(?:[^']|'')*'", texto):
            raise ValueError("string inválida ou sem fechamento")
        return texto[1:-1].replace("''", "'")
    if texto[0] == "[":
        return [escalar_yaml(parte) for parte in separar(texto[1:-1], ",")] if texto[1:-1].strip() else []
    if texto[0] == "{":
        mapa = {}
        for parte in separar(texto[1:-1], ",") if texto[1:-1].strip() else []:
            chave, valor = par_yaml(parte)
            if chave in mapa:
                raise ValueError("chave duplicada")
            mapa[chave] = escalar_yaml(valor)
        return mapa
    if texto in ("true", "false", "null", "~"):
        return {"true": True, "false": False, "null": None, "~": None}[texto]
    if re.fullmatch(r"[-+]?\d+", texto):
        return int(texto)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", texto):
        return float(texto)
    if texto[0] in "&*!|>@`%" or texto in ("---", "...") or ": " in texto or any(c in texto for c in "{}[]"):
        raise ValueError("sintaxe não suportada")
    return texto


def par_yaml(texto: str) -> tuple[str, str]:
    partes = separar(texto, ":")
    if len(partes) < 2 or not partes[0]:
        raise ValueError("esperado chave: valor")
    chave = escalar_yaml(partes[0])
    if not isinstance(chave, str):
        raise ValueError("chave deve ser string")
    return chave, ":".join(partes[1:]).strip()


def ler_yaml(texto: str) -> dict:
    linhas = []
    for numero_linha, linha in enumerate(texto.splitlines(), 1):
        try:
            if "\t" in linha[:len(linha) - len(linha.lstrip())]:
                raise ValueError("indentação com tabulação não suportada")
            conteudo = separar(linha.strip(), "#")[0]
            if conteudo:
                linhas.append((len(linha) - len(linha.lstrip()), conteudo, numero_linha))
        except ValueError as erro:
            raise ValueError(f"linha {numero_linha}: {erro}") from erro

    def bloco(indice, nivel):
        lista = linhas[indice][1].startswith("- ")
        resultado = [] if lista else {}
        while indice < len(linhas) and linhas[indice][0] >= nivel:
            recuo, conteudo, numero_linha = linhas[indice]
            try:
                if recuo != nivel or conteudo.startswith("- ") != lista:
                    raise ValueError("indentação ou coleção incompatível")
                if lista:
                    resultado.append(escalar_yaml(conteudo[2:]))
                    indice += 1
                else:
                    chave, valor = par_yaml(conteudo)
                    if chave in resultado:
                        raise ValueError("chave duplicada")
                    indice += 1
                    if valor:
                        resultado[chave] = escalar_yaml(valor)
                    elif indice < len(linhas) and linhas[indice][0] > nivel:
                        resultado[chave], indice = bloco(indice, linhas[indice][0])
                    else:
                        resultado[chave] = {}
            except ValueError as erro:
                if str(erro).startswith("linha "):
                    raise
                raise ValueError(f"linha {numero_linha}: {erro}") from erro
        return resultado, indice

    if not linhas:
        return {}
    if linhas[0][0] != 0:
        raise ValueError(f"linha {linhas[0][2]}: raiz deve começar sem indentação")
    resultado, _ = bloco(0, 0)
    if not isinstance(resultado, dict):
        raise ValueError("linha 1: raiz deve ser mapa")
    return resultado
