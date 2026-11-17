# dev-amys-ai

Um kit de IA para engenharia de soluções digitais (backend, frontend, design, infra) que funciona
com **qualquer agente** (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode/Kilo) e
**qualquer modelo** (Claude, GPT, Gemini, modelos locais no Ollama, centenas no OpenRouter).

Você escreve skills, processo e padrões **uma vez**, aqui, e instala em todos os seus projetos.

```text
dev-amys-ai (este repositório)                 seu projeto
  skills/          ─┐                            .agents/skills/  .claude/skills/
  processo/         │                            .kit-ia/processo/   (como trabalhar)
  padroes/          ├── python kit.py instalar ─> .kit-ia/padroes/    (o que é bom código)
  modelos/          │                            .kit-ia/modelos/    (task, CI)
  config/mcp.json   │                            .kit-ia/projeto.yaml (branches, gates, comandos)
  modelo AGENTS.md ─┘                            AGENTS.md + CLAUDE.md, .mcp.json e afins

                     python kit.py executar ───> qualquer modelo por API
```

Versão atual: **0.1.2** ([CHANGELOG.md](CHANGELOG.md)).

## As peças

| Peça | O que é | Onde |
|---|---|---|
| Instruções | O manual de cada projeto, lido em toda sessão | `AGENTS.md` do projeto |
| Processo | Como uma demanda vira task, quem faz o quê, gates, Git, custo | [processo/](processo/00-nucleo.md) |
| Padrões | Regras técnicas por área | [padroes/](padroes/README.md) |
| Skills | Receitas carregadas sob demanda (padrão Agent Skills) | [skills/](skills/) |
| MCP | Acesso a outros sistemas, traduzido para cada agente | [config/mcp.json](config/mcp.json) |
| Configuração do projeto | O que muda entre projetos: hospedagem, branches, destinos, worktrees, orçamento, gates, comandos | [templates/projeto.yaml](templates/projeto.yaml) |

Conceitos e quem lê o quê: [docs/conceitos.md](docs/conceitos.md).

## Instalar

Requisito: Python 3.10+ (nada de `pip install`).

```bash
git clone https://github.com/lucasssosa/dev-amys-ai.git
cd dev-amys-ai
python kit.py listar                                  # skills, agentes e servidores MCP
python kit.py instalar ../meu-projeto --simular       # mostra o que faria
python kit.py instalar ../meu-projeto                 # instala para todos os agentes
python kit.py instalar ../meu-projeto --agentes claude,universal
python kit.py instalar ../meu-projeto --mcp-global     # oferece executar MCP global, após confirmar
python kit.py instalar --global                       # só as skills, para todos os projetos
```

Para Codex e Antigravity (agy), a instalação mostra a seção **MCP global (rode uma vez)**.
Copie os comandos ou use `--mcp-global` e responda `s` a `Executar estes comandos? [s/N]`.
Sem essa opção e confirmação, nenhum comando global é executado; com `--simular`, o kit só
mostra os comandos, sem perguntar. `--sem-mcp` omite arquivos e comandos de MCP.
`--agentes codex` ou `--agentes antigravity`, sozinhos, também instalam as skills.
O modo `--global` continua exclusivo para skills: use uma pasta de projeto com `--mcp-global`.

Depois, no projeto, peça ao agente: **"preencha o AGENTS.md"**. A skill `iniciar-agents-md`
escreve o `AGENTS.md` e preenche o `.kit-ia/projeto.yaml` a partir do código real.

Reinstalar (inclusive depois de atualizar o kit com `git pull`) é seguro:
- **Atualiza** as cópias do kit: skills, `.kit-ia/processo/`, `.kit-ia/padroes/`, `.kit-ia/modelos/`.
- **Nunca sobrescreve** o que é do projeto: `AGENTS.md`, `CLAUDE.md`, `.kit-ia/projeto.yaml`, uma
  skill própria com o mesmo nome, servidores MCP nos arquivos locais (a não ser com `--forcar`).
- Os comandos de MCP global seguem as regras de cada CLI; confira-os antes de confirmar a execução.
- Grava a versão do kit em `.kit-ia/VERSAO`.

Projetos podem estar em qualquer provedor (GitHub, Azure DevOps, GitLab ou nenhum): isso é
configurado em `hospedagem` no `projeto.yaml`. Modelos de CI em [modelos/ci/](modelos/ci/).

## Skills incluídas

| Skill | Quando usar |
|---|---|
| `iniciar-agents-md` | Começar a usar IA num projeto: gera o AGENTS.md e preenche o projeto.yaml |
| `planejar` | Antes de codar: opções, testes, passos pequenos; espera aprovação |
| `verificar` | Antes de dizer "pronto": build, testes, execução real e caso de erro |
| `revisar` | Antes do commit ou do pull request: bugs, segurança, testes fracos, escopo |
| `criar-skill` | Transformar um procedimento repetido numa skill nova |

## Usar uma skill com qualquer modelo, sem agente

```bash
cp .env.exemplo .env                        # escolha o provedor (padrão: Ollama local, sem chave)
git diff | python kit.py executar revisar   # revisão de código com o modelo configurado
python kit.py executar planejar --entrada "adicionar login com Google"
```

Dois protocolos cobrem praticamente todo provedor: `openai` (Ollama, OpenRouter, OpenAI, Gemini,
LM Studio, vLLM) e `anthropic` (API nativa do Claude). Exemplos no [.env.exemplo](.env.exemplo).
Nesse modo o modelo não tem ferramentas: serve para automações de texto como revisão de diff no CI.

## Personalizar

- **Nova skill:** `python kit.py nova-skill <nome> --descricao "Faz ... Use quando ..."`, depois
  `python kit.py validar` (ou peça ao agente com a skill `criar-skill`).
- **Novo servidor MCP:** [config/mcp.json](config/mcp.json) (`http` com `url`, ou `stdio` com `comando`).
- **Agente mudou de pasta, ou chegou um agente novo:** [config/agentes.json](config/agentes.json).
- **Regra técnica nova:** no arquivo da área em `padroes/`.

## Estrutura

```text
kit.py                  CLI: listar, validar, instalar, nova-skill, executar
skills/                 skills (padrão Agent Skills)
processo/               como trabalhar; vai para .kit-ia/processo/ nos projetos
padroes/                padrões técnicos por área; vai para .kit-ia/padroes/
modelos/                modelo de task e de CI; vai para .kit-ia/modelos/
templates/              arquivos que o kit.py usa: projeto.yaml, CLAUDE.md, SKILL.md
config/                 agentes (onde cada um lê) e servidores MCP
docs/                   conceitos e documentação de uso (para pessoas)
tests/                  testes (python -m unittest discover -s tests -v)
```

## Desenvolvimento do kit

O trabalho neste repositório segue o próprio processo: veja [AGENTS.md](AGENTS.md).

```bash
python -m unittest discover -s tests -v
python kit.py validar
python kit.py instalar . --agentes claude    # usa as próprias skills aqui (cópias no .gitignore)
```

O CI do GitHub roda as duas primeiras linhas a cada push ([.github/workflows/testes.yml](.github/workflows/testes.yml)).
