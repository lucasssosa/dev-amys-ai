# dev-amys-ai

Um kit de IA para engenharia de soluções digitais (backend, frontend, design, infra) que funciona
com **qualquer agente** (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode/Kilo) e
**qualquer modelo** (Claude, GPT, Gemini, modelos locais no Ollama, centenas no OpenRouter).

Você escreve skills, processo e padrões **uma vez**, aqui, e instala em todos os seus projetos.

```text
dev-amys-ai (este repositório)                 seu projeto
  skills/          ─┐                            .agents/skills/  .claude/skills/
  processo/         │                            .kit-ia/processo/   (como trabalhar)
  padroes/          ├── python kit.py install ─> .kit-ia/padroes/    (o que é bom código)
  modelos/          │                            .kit-ia/modelos/    (task, CI)
  config/mcp.json   │                            .kit-ia/projeto.yaml (branches, gates, comandos)
  modelo AGENTS.md ─┘                            AGENTS.md + CLAUDE.md, .mcp.json e afins

                     python kit.py run ───> qualquer modelo por API
```

Versão atual: **0.3.0** ([CHANGELOG.md](CHANGELOG.md)).

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
python kit.py list                                  # skills, agentes e servidores MCP
python kit.py install ../meu-projeto --dry-run       # mostra o que faria
python kit.py install ../meu-projeto                 # instala para todos os agentes
python kit.py install ../meu-projeto --agents claude,universal
python kit.py install ../meu-projeto --mcp-global     # oferece executar MCP global, após confirmar
python kit.py install --global                       # só as skills, para todos os projetos
```

Para Codex e Antigravity (agy), a instalação mostra a seção **MCP global (rode uma vez)**.
Copie os comandos ou use `--mcp-global` e responda `s` a `Executar estes comandos? [s/N]`.
Sem essa opção e confirmação, nenhum comando global é executado; com `--dry-run`, o kit só
mostra os comandos, sem perguntar. `--no-mcp` omite arquivos e comandos de MCP.
`--agents codex` ou `--agents antigravity`, sozinhos, também instalam as skills.
O modo `--global` continua exclusivo para skills: use uma pasta de projeto com `--mcp-global`.

Depois, no projeto, peça ao agente: **"preencha o AGENTS.md"**. A skill `iniciar-agents-md`
escreve o `AGENTS.md` e preenche o `.kit-ia/projeto.yaml` a partir do código real.

Reinstalar (inclusive depois de atualizar o kit com `git pull`) é seguro:
- **Atualiza** as cópias do kit: skills, `.kit-ia/processo/`, `.kit-ia/padroes/`, `.kit-ia/modelos/`.
- **Nunca sobrescreve** o que é do projeto: `AGENTS.md`, `CLAUDE.md`, `.kit-ia/projeto.yaml`, uma
  skill própria com o mesmo nome, servidores MCP nos arquivos locais (a não ser com `--force`).
- Os comandos de MCP global seguem as regras de cada CLI; confira-os antes de confirmar a execução.
- Grava a versão do kit em `.kit-ia/VERSAO`.

Projetos podem estar em qualquer provedor (GitHub, Azure DevOps, GitLab ou nenhum): isso é
configurado em `hospedagem` no `projeto.yaml`. Modelos de CI em [modelos/ci/](modelos/ci/).

## Atualizar

Depois de baixar uma versão nova do kit, confira os projetos e atualize suas cópias:

```bash
git pull
python kit.py status
python kit.py status ../meu-projeto --details
python kit.py update --dry-run
python kit.py update
python kit.py update ../meu-projeto       # atualiza apenas este projeto registrado
```

Cada instalação local registra o caminho absoluto, os agentes, a versão e a data em
`~/.kit-ia/projetos.json` (ou `$KIT_IA_HOME/projetos.json`). Reinstalar atualiza a mesma
entrada. Instalações com `--global` ou `--dry-run` não registram projetos.
`status` resume cada projeto em uma linha; `--details` lista cópias desatualizadas,
chaves ausentes e pendências de `AGENTS.md` e `CLAUDE.md`. Um caminho explícito também
pode ser inspecionado antes de ser registrado.
As cópias com marcador de seleções anteriores de skills ou agentes também são conferidas.

`update` reinstala somente nos projetos registrados, com os agentes e as opções
`--skills` e `--no-mcp` da instalação mais recente. Preserva os arquivos do usuário
pelas mesmas regras de `install`, sem `--force` e sem executar comandos globais de MCP.
Pastas que não existem mais saem do registro com aviso; `--dry-run` apenas mostra essa
remoção e as mudanças previstas, sem gravar arquivos nem alterar o registro.

Chaves novas do `projeto.yaml` **não são inseridas automaticamente**: o `status` aponta
as que faltam no primeiro e no segundo nível. Complete-as à mão usando
[templates/projeto.yaml](templates/projeto.yaml) como referência. Essas pendências e
as de instruções próprias continuam visíveis depois da atualização até serem resolvidas.

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
git diff | python kit.py run revisar   # revisão de código com o modelo configurado
python kit.py run planejar --input "adicionar login com Google"
git diff | python kit.py run revisar --task BL-LU-3
```

Dois protocolos cobrem praticamente todo provedor: `openai` (Ollama, OpenRouter, OpenAI, Gemini,
LM Studio, vLLM) e `anthropic` (API nativa do Claude). Exemplos no [.env.exemplo](.env.exemplo).
Nesse modo o modelo não tem ferramentas: serve para automações de texto como revisão de diff no CI.

## Desinstalar de um projeto

```bash
python kit.py uninstall ../meu-projeto --dry-run
python kit.py uninstall ../meu-projeto
python kit.py uninstall ../meu-projeto --yes
python kit.py uninstall ../meu-projeto --agents claude,universal
python kit.py uninstall ../meu-projeto --mcp-global
python kit.py uninstall --global --dry-run
```

A prévia lista tudo o que será removido e pergunta `Remover? [s/N]`. `--yes` confirma
a remoção local. `--dry-run` não altera arquivos, registro nem configuração global e não
pergunta. Pastas de skills, processo, padrões e modelos precisam do marcador `.kit-ia`;
links e junções são preservados para evitar remoções fora do destino.

`AGENTS.md`, `CLAUDE.md` e `.kit-ia/projeto.yaml` só saem se forem idênticos aos modelos
gerados. Arquivos editados ficam com aviso, incluindo a seção das instruções que pode ser
retirada à mão. Entradas MCP só saem se forem idênticas à configuração do kit; servidores
próprios, opções extras e JSON inválido são preservados. Arquivos e pastas que ficarem
vazios são removidos, e o projeto sai do registro local.

Os comandos `codex mcp remove` e `agy mcp remove` são exibidos. Executá-los exige
`--mcp-global` e a confirmação separada `Executar estes comandos? [s/N]`, mesmo com
`--yes`. `--global` remove apenas skills globais com marcador. Use `--agents` para limitar
os destinos de agentes; cópias compartilhadas de processo e configuração são do projeto.

Na versão 0.3.0 a CLI passou a inglês sem apelidos em português. Consulte a tabela de
migração no [changelog](CHANGELOG.md). As mensagens e configurações continuam em português.

## Medir tokens, tempo e custo

```bash
python kit.py cost --since 2026-11-16 --by agent
python kit.py cost --by model --json
python kit.py cost --batch BL-LU-1,BL-LU-2
python kit.py cost --check-budget ../meu-projeto
python kit.py cost --project ../meu-projeto --until 2026-11-17T23:59:59Z --by day
```

O comando lê métricas locais de Claude Code (incluindo subagentes), Codex, Antigravity e
`kit.py run`, sem chamar modelos nem salvar conversas. Agrupe com `--by task`, `model`,
`agent`, `role` ou `day`. A task é detectada pela branch ou pasta; `run --task ID` tem prioridade.
`--until` inclui sessões iniciadas até o instante ISO informado; `--project` filtra o projeto
e suas worktrees. Intervalos incluem o consumo completo de sessões que cruzam os limites.
`day` agrupa pelo dia UTC do início da sessão, sem repartir tokens entre dias.
O filtro `--since` inclui o total da sessão que teve atividade desde essa data, sem estimar
uma fração de tokens. Minutos são o intervalo entre a primeira e a última atividade de cada
sessão; a soma pode incluir sessões simultâneas. O tempo de `run` é a duração da chamada.
No Codex, as diferenças entre acumulados são atribuídas ao modelo ativo em cada evento;
cache e raciocínio não são somados novamente. Os intervalos vão para o modelo do próximo
evento de uso, e o trecho final fica com o último modelo que consumiu tokens.
Se há vários modelos numa sessão Claude, cada intervalo é atribuído ao último modelo ativo,
e o tempo anterior à primeira resposta fica com o primeiro modelo.

Configure tarifas em [config/precos.json](config/precos.json), por nome exato de modelo,
com `entrada`, `saida`, `cache_leitura` e `cache_escrita` em USD por milhão de tokens.
Sem tarifa, o custo aparece como `—` (`null` no JSON); `usage.cost` do provedor tem prioridade.
O cache já faz parte da entrada normalizada: não some as colunas de cache ao total de tokens.
Tokens desconhecidos aparecem como `—`; `*` indica medição parcial. O relatório mostra
a estimativa em `Tokens` e o limite superior conservador em `Limite tokens`, com os
equivalentes de tempo. No JSON: `tokens`, `minutos`, `limite_superior_tokens`,
`limite_superior_minutos` e `medicao_incompleta`.

`run` registra somente data, protocolo, URL sem credenciais/query, modelo, uso, duração,
pasta e task em `~/.kit-ia/uso.jsonl`. Falha na gravação ou telemetria inválida apenas emite
aviso, preservando a resposta do modelo. Os caminhos são
substituíveis por `KIT_IA_HOME`, `KIT_IA_CLAUDE_DIR` (padrão `~/.claude/projects`),
`KIT_IA_CODEX_DIR` (`~/.codex/sessions`) e `KIT_IA_ANTIGRAVITY_DIR` (`~/.gemini/antigravity`).

O orçamento lê `.kit-ia/projeto.yaml` do projeto indicado, filtra sessões dentro dessa pasta
e das worktrees registradas pelo Git para o mesmo repositório e compara cada task com
`orcamento.por_task.tokens` e `minutos` usando somente o limite superior, nunca a estimativa.
Claude usa o maior valor de cada contador por resposta; Codex usa os maiores acumulados
da sessão, sem subtrações, atribuindo a sessão inteira a cada task tocada.
Retorna 1 ao exceder ou quando há medição incompleta, e 0 somente com medição completa
sem excesso. Registros ilegíveis sem contexto bloqueiam a verificação, pois não é possível
descartar que pertençam ao projeto. Na dúvida, o erro é para o lado de "estourou".
Os aliases `cost` e `--check-budget` aceitam os mesmos argumentos.
O leitor aceita mapas indentados/inline, listas simples, strings, números e comentários;
sintaxe fora desse subconjunto produz erro com a linha. Não interrompe agentes em execução.

Limitações: Antigravity não expõe tokens em campos verificados, e seu tempo cobre apenas
o último envio até a última alteração. Bancos com acesso restrito podem exigir leitura
imutável (com aviso de possível ausência do WAL). Acumulados regressivos do Codex geram
aviso e uso parcial, com custo desconhecido. OpenCode/Kilo ainda não têm leitor.

## Personalizar

- **Nova skill:** `python kit.py new-skill <nome> --description "Faz ... Use quando ..."`, depois
  `python kit.py validate` (ou peça ao agente com a skill `criar-skill`).
- **Novo servidor MCP:** [config/mcp.json](config/mcp.json) (`http` com `url`, ou `stdio` com `comando`).
- **Agente mudou de pasta, ou chegou um agente novo:** [config/agentes.json](config/agentes.json).
- **Regra técnica nova:** no arquivo da área em `padroes/`.

## Estrutura

```text
kit.py                  CLI: listar, validar, instalar, nova-skill, executar, custo
custo.py                leitura e agregação das métricas locais de uso
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
python kit.py validate
python kit.py install . --agents claude    # usa as próprias skills aqui (cópias no .gitignore)
```

O CI do GitHub roda as duas primeiras linhas a cada push ([.github/workflows/testes.yml](.github/workflows/testes.yml)).
