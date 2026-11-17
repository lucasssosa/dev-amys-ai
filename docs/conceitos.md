# Conceitos: o que fica em volta do modelo

Um agente de código (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode) é um **modelo**
dentro de um **laço**: ele lê o pedido, escolhe uma ferramenta (ler arquivo, rodar comando, chamar
MCP), vê o resultado e repete até terminar. O resultado depende menos do modelo e mais do que vai
em volta dele. Este kit organiza essas peças para que elas não dependam de um agente nem de um modelo.

## As camadas

| Camada | O que é | Quando é carregada | Agnóstica? | No kit |
|---|---|---|---|---|
| **Instruções** (`AGENTS.md`) | Regras e comandos do projeto | Sempre, no início da sessão | Sim (padrão aberto) | modelo instalado em todo projeto |
| **Skills** (`SKILL.md`) | Procedimentos passo a passo | Só quando o pedido combina com a `description` | Sim (padrão Agent Skills) | `skills/` |
| **MCP** | Ferramentas e dados de outros sistemas | Ferramentas listadas no início; usadas quando o modelo decide | Protocolo sim; arquivo de config não | `config/mcp.json` → traduzido por agente |
| **Processo** | Como trabalhar: fluxo, papéis, gates, Git, custo | Núcleo sempre; o resto sob demanda | Sim (Markdown) | `processo/` → `.kit-ia/processo/` |
| **Padrões** | O que é bom código, por área | Sob demanda, pela área da demanda | Sim (Markdown) | `padroes/` → `.kit-ia/padroes/` |
| **Configuração do projeto** | Branches, destinos, gates, comandos, orçamento | Sempre | Sim (YAML) | `.kit-ia/projeto.yaml` |
| **Hooks** | Comando que roda **sempre** num evento | Em todo evento configurado | Hooks de Git sim; hooks de agente não | hooks de Git (ainda não implementado) |
| **Permissões** | O que roda sem perguntar | Sempre | Não (cada agente tem o seu) | fora do kit, por enquanto |
| **Modelo** | O "cérebro" | | Trocável | `kit.py run` + `.env` |

### Instruções vs skill vs MCP vs hook

- Vale **sempre**? → `AGENTS.md` ("Controller não tem regra de negócio").
- É um **procedimento** que acontece às vezes? → **skill** ("como liberar uma versão").
- Precisa **acessar outro sistema**? → **MCP** ("consultar o Jira", "ler a doc atual da biblioteca").
- Precisa acontecer **sem depender do modelo lembrar**? → **hook** ou CI ("rodar o formatador depois de editar").

## Skills: o carregamento progressivo

1. No início, o agente lê só o `name` e a `description` de cada skill (poucas linhas cada).
2. Quando o pedido combina com uma descrição, ele lê o `SKILL.md` inteiro.
3. Arquivos de apoio (`referencias/`, `scripts/`, `modelo-AGENTS.md`) só são lidos quando um passo pede.

Por isso a **descrição** é a parte mais importante: ela decide se a skill é usada.
E por isso dá para ter dezenas de skills sem encher o contexto do modelo.

Formato (padrão aberto, [agentskills.io](https://agentskills.io)):

```markdown
---
name: verificar            # igual ao nome da pasta, kebab-case, até 64 caracteres
description: O que faz. Use quando ...   # até 1024 caracteres
---

# Corpo em Markdown: objetivo, passos, formato da resposta, o que não fazer.
```

## Quem lê o quê (novembro de 2026)

Esses caminhos mudam com as versões dos agentes. Exceto pela medição indicada abaixo, as informações
vêm de fontes secundárias: se algo parar de funcionar, confira na documentação do agente e
ajuste `config/agentes.json`.

| Agente | Instruções | Skills no projeto | MCP |
|---|---|---|---|
| Claude Code | `CLAUDE.md` (o kit põe `@AGENTS.md` dentro) | `.claude/skills/` | `.mcp.json` |
| Codex CLI | `AGENTS.md` | `.agents/skills/` | Global, via `codex mcp add` |
| Antigravity CLI (agy) | `AGENTS.md` | `.agents/skills/` | Global, via `agy mcp add` |
| Cursor | `AGENTS.md` | `.agents/skills/`, `.cursor/skills/` | `.cursor/mcp.json` |
| Copilot (VS Code) | `AGENTS.md` | `.agents/skills/`, `.github/skills/` | `.vscode/mcp.json` |
| Gemini CLI (legado) | `GEMINI.md` (o kit configura para ler `AGENTS.md` também) | (confirmar) | `.gemini/settings.json` |
| OpenCode / Kilo | `AGENTS.md` | `.agents/skills/` | `opencode.json` |

MCP global verificado em 2026-11-16 (Codex 0.167, agy 1.4.2): na medição, o Codex ignorou
o `.codex/config.toml` do projeto mesmo com o projeto confiável; o Antigravity também carregou
MCP apenas globalmente. O kit mostra os comandos em `install <projeto>` e só oferece executá-los
com `--mcp-global`, mediante resposta `s`. Cabeçalhos no Codex exigem configuração à mão.
O sandbox do Codex no Windows não lê `AppData\Local\Temp`: use uma pasta temporária acessível
na área de trabalho, configurada em TEMP/TMP.

Por que o kit escreve `CLAUDE.md` com `@AGENTS.md` em vez de confiar que o Claude Code lê o
`AGENTS.md`: as fontes divergem sobre isso, e a importação explícita funciona em todas as versões.

## Processo e padrões: por que dois tipos de documento

- O **processo** (`processo/`) é igual em todo projeto: como uma demanda vira task, quem faz o
  quê, o que precisa estar verde antes de seguir. O `00-nucleo.md` é lido em toda sessão
  (o `AGENTS.md` do projeto manda ler); os outros arquivos só quando a etapa pede.
- Os **padrões** (`padroes/`) dependem da área: uma landing page nunca lê `mensageria.md`.
- O que muda de projeto para projeto (branches, homologação, comandos, orçamento) não fica em
  nenhum dos dois: fica no `.kit-ia/projeto.yaml`. Assim o processo continua o mesmo.

## Agnóstico de modelo, na prática

- **Dentro de um agente:** o modelo é escolhido no próprio agente. OpenCode, Kilo, Cursor e Copilot
  aceitam vários provedores; Claude Code usa modelos Claude; Codex usa modelos OpenAI.
  Como skills, AGENTS.md e MCP são padrões abertos, trocar de agente não exige reescrever nada.
- **Fora de um agente:** `python kit.py run <skill>` envia a skill como instrução de sistema
  para qualquer API. Dois formatos cobrem quase todo provedor:
  - `openai` → `POST {url}/chat/completions` (Ollama, OpenRouter, OpenAI, Gemini, LM Studio, vLLM);
  - `anthropic` → `POST {url}/messages` (API nativa do Claude).

## Segurança

- Nunca coloque chave em skill, `AGENTS.md` ou `config/mcp.json`: use `.env` ou variável de ambiente.
- Um servidor MCP executa ações de verdade: instale só os que você conhece, e prefira que as
  ferramentas que alteram dados peçam confirmação.
- **Injeção de prompt:** conteúdo lido de fora (páginas, issues, respostas de API, diffs de
  terceiros) pode conter instruções. Trate como dado, não como ordem.
