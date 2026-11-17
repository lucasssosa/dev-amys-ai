"""Métricas locais, sem chamadas a modelos e sem persistir conteúdo de conversas."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timedelta, timezone
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
    extras = {}
    if protocolo == "anthropic":
        entrada, saida = uso.get("input_tokens"), uso.get("output_tokens")
        leitura, escrita = uso.get("cache_read_input_tokens", 0), uso.get("cache_creation_input_tokens", 0)
        if any(numero(valor) is None for valor in (entrada, saida, leitura, escrita)):
            extras = {"parcial": True, "custo_confiavel": False}
        cache = (numero(leitura) or 0) + (numero(escrita) or 0)
        # Cache conhecido comprova entrada mínima mesmo sem o contador de entrada sem cache.
        if numero(entrada) is not None or cache:
            entrada = (numero(entrada) or 0) + cache
    else:
        entrada = uso.get("prompt_tokens", resposta.get("prompt_eval_count"))
        saida = uso.get("completion_tokens", resposta.get("eval_count"))
        detalhes = uso.get("prompt_tokens_details")
        if detalhes is not None and not isinstance(detalhes, dict):
            raise ValueError("telemetria inválida: prompt_tokens_details precisa ser um mapa")
        leitura = (detalhes or {}).get("cached_tokens", 0)
        escrita = 0
        if numero(entrada) is None or numero(saida) is None or numero(leitura) is None:
            extras = {"parcial": True, "custo_confiavel": False}
        if numero(leitura) is not None:
            entrada = max(numero(entrada) or 0, leitura) if numero(entrada) is not None or leitura else None
    return {"entrada": numero(entrada), "saida": numero(saida),
            "cache_leitura": numero(leitura), "cache_escrita": numero(escrita),
            "custo_usd": numero(uso.get("cost")), **extras}


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
                    else:
                        avisos.append(f"{arquivo.name}: registro JSON não é um mapa")
                except ValueError:
                    avisos.append(f"{arquivo.name}: linha JSON inválida ignorada")
    except (OSError, UnicodeError):
        avisos.append(f"{arquivo.name}: leitura indisponível")


def texto_metrica(valor, padrao, arquivo, avisos):
    if isinstance(valor, str):
        return valor
    avisos.append(f"{arquivo.name}: contexto de medição inválido")
    return padrao


def registro(agente, modelo, papel, pasta, branch, inicio, fim, uso, **extras):
    return {"agente": agente, "modelo": modelo or "(desconhecido)", "papel": papel,
            "pasta": pasta, "task": detectar_task(branch, pasta), "inicio": inicio,
            "fim": fim, "entrada": uso.get("entrada"), "saida": uso.get("saida"),
            "cache_leitura": uso.get("cache_leitura", 0), "cache_escrita": uso.get("cache_escrita", 0),
            "custo_usd": uso.get("custo_usd"),
            **{chave: uso[chave] for chave in ("parcial", "custo_confiavel") if chave in uso}, **extras}


def ler_claude(pasta: Path, avisos: list) -> list:
    registros, respostas = [], {}
    for arquivo in sorted(pasta.rglob("*.jsonl")):
        inicio_avisos = len(avisos)
        grupos = {}
        relacionados = {}
        primeira = ultima = None
        atual, anterior, pendentes = None, None, 0
        for linha in linhas_json(arquivo, avisos):
            # Distribuir os intervalos preserva a duração da sessão sem duplicá-la por modelo.
            instante = data(linha.get("timestamp"))
            if "timestamp" in linha and instante is None:
                avisos.append(f"{arquivo.name}: horário inválido")
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
            if not isinstance(mensagem, dict):
                avisos.append(f"{arquivo.name}: mensagem sem estrutura de medição verificável")
                continue
            if "usage" not in mensagem:
                continue
            identificador = linha.get("requestId") or mensagem.get("id")
            if identificador is not None and not isinstance(identificador, str):
                avisos.append(f"{arquivo.name}: identificador de resposta inválido")
                identificador = None
            uso = mensagem["usage"] if isinstance(mensagem["usage"], dict) else {}
            if identificador and identificador in respostas:
                grupo, consolidado, instantes, maximos = respostas[identificador]
                grupo["inicio"] = min(filter(None, (grupo["inicio"], primeira)), default=None)
                grupo["fim"] = max(filter(None, (grupo["fim"], ultima)), default=None)
            else:
                papel = "subagente" if linha.get("isSidechain") or "subagents" in arquivo.parts else "principal"
                local = texto_metrica(linha.get("cwd", ""), "", arquivo, avisos)
                branch = texto_metrica(linha.get("gitBranch", ""), "", arquivo, avisos)
                modelo = texto_metrica(mensagem.get("model", ""), "", arquivo, avisos)
                chave = (modelo, papel, local, branch)
                if chave not in grupos:
                    grupos[chave] = registro("claude", chave[0], papel, local, branch, None, None,
                                            {"entrada": 0, "saida": 0}, minutos=0)
                grupo = grupos[chave]
                atual = chave
                grupo["minutos"] += pendentes
                pendentes = 0
                consolidado, instantes, maximos = {}, {}, {}
                # Sem identificador, não há evidência de duplicação: cada linha conta separadamente.
                respostas[identificador or object()] = (grupo, consolidado, instantes, maximos)
            relacionados[id(grupo)] = grupo
            if not identificador or instante is None:
                grupo["medicao_incompleta"] = True
            if instante is None:
                grupo["janela_incerta"] = True
            for campo in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                          "cache_creation_input_tokens"):
                if campo not in uso and campo.startswith("cache_") and campo in consolidado:
                    continue
                valor = numero(uso.get(campo, 0 if campo.startswith("cache_") else None))
                if valor is None:
                    grupo["parcial"] = True
                    grupo["custo_confiavel"] = False
                else:
                    maximos[campo] = max(maximos.get(campo, 0), valor)
                if valor is None:
                    continue
                if (campo not in consolidado or instante is None or instantes[campo] is None
                      or instante >= instantes[campo]):
                    # O horário por contador permite preencher lacunas com cópias fora de ordem,
                    # sem que um null posterior apague consumo nem uma cópia antiga o substitua.
                    consolidado[campo], instantes[campo] = valor, instante
        for grupo in relacionados.values():
            grupo["inicio"] = min(filter(None, (grupo["inicio"], primeira)), default=None)
            grupo["fim"] = max(filter(None, (grupo["fim"], ultima)), default=None)
            grupo.setdefault("sessoes_tempo", {})[str(arquivo)] = (
                (ultima - primeira).total_seconds() / 60 if primeira and ultima else 0)
        sinalizar_leitura(relacionados if relacionados else grupos, arquivo, avisos,
                          inicio_avisos, "claude", primeira, ultima)
        registros.extend(grupos.values())
    # Somar só após consolidar evita contar tanto a parcial quanto a resposta final.
    for grupo, uso, _, maximos in respostas.values():
        grupo["limite_superior_tokens"] = grupo.get("limite_superior_tokens", 0) + sum(maximos.values())
        for destino, origem in (("entrada", "input_tokens"), ("saida", "output_tokens"),
                                ("cache_leitura", "cache_read_input_tokens"),
                                ("cache_escrita", "cache_creation_input_tokens")):
            grupo[destino] += uso.get(origem, 0)
    for grupo in registros:
        # O Claude informa entrada sem cache; normalizamos para o total de entrada.
        if grupo["entrada"] is not None:
            grupo["entrada"] += (grupo["cache_leitura"] or 0) + (grupo["cache_escrita"] or 0)
    return registros


def ler_codex(pasta: Path, avisos: list) -> list:
    registros = []
    for arquivo in sorted(pasta.rglob("*.jsonl")):
        inicio_avisos = len(avisos)
        primeira = ultima = None
        local = branch = modelo = ""
        papel, anterior, grupos = "principal", {}, {}
        atividades, maximos = [], {}
        for linha in linhas_json(arquivo, avisos):
            instante = data(linha.get("timestamp"))
            if "timestamp" in linha and instante is None:
                avisos.append(f"{arquivo.name}: horário inválido")
            if instante:
                primeira = min(primeira or instante, instante)
                ultima = max(ultima or instante, instante)
            # Valores vazios inválidos também precisam bloquear a aprovação do orçamento.
            carga = linha.get("payload")
            if not isinstance(carga, dict):
                avisos.append(f"{arquivo.name}: payload inválido")
                continue
            if linha.get("type") in ("session_meta", "turn_context"):
                local = texto_metrica(carga.get("cwd", local), local, arquivo, avisos)
                modelo = texto_metrica(carga.get("model", modelo), modelo, arquivo, avisos)
                git = carga.get("git") or {}
                if not isinstance(git, dict):
                    avisos.append(f"{arquivo.name}: contexto Git inválido")
                    git = {}
                branch = texto_metrica(git.get("branch", branch), branch, arquivo, avisos)
            if linha.get("type") == "session_meta":
                inicio = data(carga.get("timestamp"))
                if inicio:
                    primeira = min(primeira or inicio, inicio)
                papel = "subagente" if isinstance(carga.get("source"), dict) or carga.get("agent_role") else "principal"
            elif linha.get("type") == "event_msg" and carga.get("type") == "token_count":
                info = carga.get("info")
                total = info.get("total_token_usage") if isinstance(info, dict) else None
                if info is not None and (not isinstance(total, dict) or not total):
                    avisos.append(f"{arquivo.name}: uso Codex inválido")
                if isinstance(total, dict) and total:
                    for campo in ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens"):
                        valor = numero(total.get(campo))
                        if valor is not None:
                            maximos[campo] = max(maximos.get(campo, 0), valor)
                    # Cache é parte da entrada; sozinho já comprova esse consumo mínimo.
                    entrada = numero(total.get("input_tokens"))
                    cache = numero(total.get("cached_input_tokens"))
                    incompleto = entrada is None or numero(total.get("output_tokens")) is None
                    if entrada is None and cache:
                        total = {**total, "input_tokens": cache}
                    # O acumulado inclui os modelos anteriores; só o delta pertence ao atual.
                    deltas = {}
                    for destino, origem in (("entrada", "input_tokens"), ("saida", "output_tokens"),
                                            ("cache_leitura", "cached_input_tokens")):
                        valor = numero(total.get(origem, 0 if destino == "cache_leitura" else None))
                        previo = anterior.get(destino, 0)
                        delta = valor - previo if valor is not None else None
                        if delta is not None and delta < 0:
                            delta = None
                            avisos.append(f"{arquivo.name}: acumulado Codex regrediu; uso parcial")
                        deltas[destino] = delta
                        # O maior acumulado é um limite inferior comprovado. Após uma regressão,
                        # só o que ultrapassa esse máximo é consumo adicional verificável.
                        if valor is not None:
                            anterior[destino] = max(previo, valor)
                    chave = (modelo, papel, local, branch)
                    if any(valor != 0 for valor in deltas.values()) or chave not in grupos:
                        if chave not in grupos:
                            grupos[chave] = registro("codex", modelo, papel, local, branch, None, None,
                                                      {"entrada": 0, "saida": 0}, minutos=0)
                        grupo = grupos[chave]
                        grupo["custo_confiavel"] = grupo.get("custo_confiavel", True) and all(
                            valor is not None for valor in deltas.values())
                        grupo["parcial"] = grupo.get("parcial", False) or not grupo["custo_confiavel"]
                        if incompleto:
                            grupo["parcial"], grupo["custo_confiavel"] = True, False
                        if instante is None:
                            grupo["medicao_incompleta"] = True
                            grupo["janela_incerta"] = True
                        for campo, valor in deltas.items():
                            grupo[campo] += valor or 0
                        atividades.append((chave, instante))
        # O intervalo acompanha modelo, pasta, branch e papel do próximo evento de uso.
        anterior_instante = primeira
        for nome, instante in atividades:
            if instante and anterior_instante:
                grupos[nome]["minutos"] += max(0, (instante - anterior_instante).total_seconds() / 60)
                anterior_instante = max(anterior_instante, instante)
        if atividades and ultima and anterior_instante:
            grupos[atividades[-1][0]]["minutos"] += max(0, (ultima - anterior_instante).total_seconds() / 60)
        for grupo in grupos.values():
            grupo["inicio"], grupo["fim"] = primeira, ultima
        sinalizar_leitura(grupos, arquivo, avisos, inicio_avisos, "codex", primeira, ultima,
                          local, branch, modelo)
        # Não se subtraem acumulados no orçamento. Cada task tocada recebe a sessão inteira;
        # a atribuição exata entre tasks/modelos não é demonstrável por snapshots parciais.
        limite = max(maximos.get("input_tokens", 0), maximos.get("cached_input_tokens", 0))
        limite = max(limite + maximos.get("output_tokens", 0), maximos.get("total_tokens", 0))
        for grupo in grupos.values():
            grupo["sessao_orcamento"] = str(arquivo)
            grupo["limite_superior_tokens"] = limite
            grupo["limite_superior_minutos"] = ((ultima - primeira).total_seconds() / 60
                                                 if primeira and ultima else 0)
        registros.extend(grupos.values())
    return registros


def sinalizar_leitura(grupos, arquivo, avisos, inicio_avisos, agente, inicio, fim,
                      local="", branch="", modelo=""):
    """Uma leitura sem métricas verificáveis não pode desaparecer da verificação."""
    if not grupos:
        grupos[None] = registro(agente, modelo, "principal", local, branch, inicio, fim, {},
                                medicao_incompleta=True)
    for grupo in grupos.values():
        grupo["janela_incerta"] = grupo.get("janela_incerta", False) or len(avisos) > inicio_avisos
        grupo["medicao_incompleta"] = (len(avisos) > inicio_avisos or not grupo["pasta"]
                                         or inicio is None or fim is None
                                         or grupo.get("medicao_incompleta", False))


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
        return [registro("antigravity", "", "principal", "", "", None, None, {}, medicao_incompleta=True)]
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
    inicio_avisos = len(avisos)
    for linha in linhas_json(arquivo, avisos):
        inicio_linha = len(avisos)
        inicio = data(linha.get("data"))
        duracao = numero(linha.get("duracao_segundos")) or 0
        # O fim inclui a duração para que o filtro de data não oculte chamadas em andamento à meia-noite.
        fim = inicio + timedelta(seconds=duracao) if inicio else None
        local = texto_metrica(linha.get("pasta", ""), "", arquivo, avisos)
        modelo = texto_metrica(linha.get("modelo", ""), "", arquivo, avisos)
        task = texto_metrica(linha.get("task", ""), "", arquivo, avisos)
        item = registro("kit", modelo, "executar", local, "", inicio, fim,
                        {chave: numero(linha.get(chave)) for chave in
                         ("entrada", "saida", "cache_leitura", "cache_escrita", "custo_usd")},
                        parcial=linha.get("parcial", False), custo_confiavel=linha.get("custo_confiavel", True))
        item["task"] = task or item["task"]
        item["minutos"] = duracao / 60
        item["medicao_incompleta"] = (inicio is None or numero(linha.get("duracao_segundos")) is None
                                        or len(avisos) > inicio_linha or not local)
        registros.append(item)
    if len(avisos) > inicio_avisos:
        registros.append(registro("kit", "", "executar", "", "", None, None, {}, medicao_incompleta=True))
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
    grupos, sessoes, tempos = {}, set(), {}
    for item in registros:
        # O dia é o início UTC da sessão; não repartimos tokens sem medição por dia.
        if por == "dia":
            chave = item["inicio"].astimezone(timezone.utc).date().isoformat() if item["inicio"] else "(sem data)"
        else:
            chave = item[por]
        if chave not in grupos:
            grupos[chave] = {por: chave, "entrada": 0, "saida": 0, "cache_leitura": 0,
                             "cache_escrita": 0, "tokens": 0, "minutos": 0, "custo_usd": 0,
                             "limite_superior_tokens": 0, "limite_superior_minutos": 0,
                             "medicao_incompleta": False,
                             "parcial": False, "uso_conhecido": False}
        grupo = grupos[chave]
        grupo["parcial"] |= item.get("parcial", False)
        grupo["uso_conhecido"] |= item.get("entrada") is not None or item.get("saida") is not None
        for campo in ("entrada", "saida", "cache_leitura", "cache_escrita"):
            if item.get(campo) is None:
                grupo["parcial"] = True
            grupo[campo] += item.get(campo) or 0
        grupo["tokens"] = grupo["entrada"] + grupo["saida"]
        sessao = (chave, item.get("sessao_orcamento"))
        contar_limite = not item.get("sessao_orcamento") or sessao not in sessoes
        if contar_limite:
            grupo["limite_superior_tokens"] += item.get("limite_superior_tokens",
                max(item.get("entrada") or 0, item.get("cache_leitura") or 0) + (item.get("saida") or 0))
            sessoes.add(sessao)
        grupo["medicao_incompleta"] |= (item.get("medicao_incompleta", False)
                                        or item.get("parcial", False)
                                        or item.get("entrada") is None or item.get("saida") is None)
        minutos = item.get("minutos", max(0, (item["fim"] - item["inicio"]).total_seconds() / 60)
                           if item["inicio"] and item["fim"] else 0)
        if item.get("sessoes_tempo"):
            for sessao_tempo, duracao in item["sessoes_tempo"].items():
                chave_tempo = (chave, sessao_tempo)
                tempos[chave_tempo] = max(tempos.get(chave_tempo, 0), duracao)
        elif contar_limite:
            grupo["limite_superior_minutos"] += item.get("limite_superior_minutos", minutos)
        if "minutos" in item:
            grupo["minutos"] += item["minutos"]
        elif item["inicio"] and item["fim"]:
            grupo["minutos"] += max(0, (item["fim"] - item["inicio"]).total_seconds() / 60)
        valor = calcular_custo(item, precos)
        grupo["custo_usd"] = None if valor is None or grupo["custo_usd"] is None else grupo["custo_usd"] + valor
    for (chave, _), duracao in tempos.items():
        grupos[chave]["limite_superior_minutos"] += duracao
    for grupo in grupos.values():
        if not grupo.pop("uso_conhecido"):
            for campo in ("tokens", "entrada", "saida", "cache_leitura", "cache_escrita"):
                grupo[campo] = None
    return sorted(grupos.values(), key=lambda item: item["tokens"] or 0, reverse=True)


def separar(texto: str, delimitador: str, limite: int | None = None) -> list[str]:
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
        elif caractere == delimitador and not pilha and (limite is None or len(partes) < limite):
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
    # Os dois-pontos do valor pertencem ao escalar e precisam chegar intactos à validação.
    partes = separar(texto, ":", limite=1)
    if len(partes) < 2 or not partes[0]:
        raise ValueError("esperado chave: valor")
    chave = escalar_yaml(partes[0])
    if not isinstance(chave, str):
        raise ValueError("chave deve ser string")
    return chave, partes[1]


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
