# Changelog

## [0.3.1] - 2026-11-17

### Adicionado

- Processo e skills orientam consultar APIs externas na documentação da versão usada pelo
  Context7 ou outro MCP de documentação; sem ele, na documentação ou no código instalado.
- Tasks incluem o campo obrigatório "Padrões a seguir", preenchido pelo coordenador conforme
  as áreas do projeto e o tipo da task e lido pelo executor antes de editar.
- `install` destaca o Context7 como recomendado e mostra o comando opcional do Claude Code
  com escopo de usuário, sem executá-lo. MCP global de Codex e Antigravity mantém a confirmação.

### Corrigido

- Executor despachado com task aprovada ou devolvida pelo revisor executa sem pedir nova
  aprovação: a task é o plano aprovado.

## [0.3.0] - 2026-11-17

### Alterado

- **Quebra de compatibilidade:** comandos e opções da CLI passam a inglês, sem apelidos
  em português. Mensagens, nomes internos, skills e chaves do projeto continuam em português.

| Comando anterior | Comando novo |
| --- | --- |
| listar | list |
| validar | validate |
| instalar | install |
| nova-skill | new-skill |
| executar | run |
| custo | cost |
| status | status |
| atualizar | update |

As opções abaixo recebem o prefixo `--` em ambos os nomes:

| Opção anterior | Opção nova |
| --- | --- |
| simular | dry-run |
| forcar | force |
| agentes | agents |
| sem-mcp | no-mcp |
| entrada | input |
| protocolo | protocol |
| modelo | model |
| descricao | description |
| versao | version |
| desde | since |
| ate | until |
| por | by |
| lote | batch |
| projeto | project |
| detalhes | details |
| verificar-orcamento | check-budget |

- Os valores de `--by` passam de `task, modelo, agente, papel, dia` para
  `task, model, agent, role, day`. As chaves dos relatórios JSON continuam em português.

### Adicionado

- `uninstall <projeto> [--agents ...] [--dry-run] [--yes] [--mcp-global]` remove
  skills e cópias com marcador, arquivos idênticos aos modelos e entradas MCP idênticas
  às geradas pelo kit; preserva edições do usuário com aviso e tira o projeto do registro.
- A prévia lista remoções e pastas que ficarão vazias; a confirmação padrão é negativa.
  `--dry-run` não escreve nem pergunta. MCP global exige opção e confirmação próprias,
  inclusive com `--yes`. `uninstall --global` remove só skills globais com marcador.
- `cost --until`, `--project` e `--by day`: filtros de intervalo e projeto e agrupamento
  pelo dia UTC de início da sessão, mantendo o consumo completo medido.

### Corrigido

- Workflow de testes, exemplo de ambiente, comentário do Git e conceitos usam os
  comandos em inglês, completando a migração e restaurando a validação no CI.
- `uninstall` bloqueia reparse points também no Python 3.10/3.11 e confere se o
  destino físico permanece dentro da pasta autorizada antes de remover arquivos.
- `cost` rejeita projetos divergentes entre `--project` e `--check-budget`, impedindo
  que o filtro oculte o consumo do projeto cujo orçamento está sendo verificado.

## [0.2.0] - 2026-11-17

- Instalações concorrentes preservam todas as entradas do registro; a remoção de pastas
  inexistentes também preserva registros incluídos durante a atualização.
- `status` confere cópias com marcador de seleções anteriores de skills e agentes.
- Instalações locais registram projetos, agentes, versão e data em `KIT_IA_HOME/projetos.json`.
  Novos comandos `status [projeto] [--details]` e `update [projeto] [--dry-run]`
  identificam cópias e configurações pendentes e atualizam os projetos registrados,
  preservando arquivos do usuário e removendo do registro pastas inexistentes.
- Payload Codex inválido marca medição incompleta mesmo após registros de uso válidos,
  preservando os tokens conhecidos e impedindo aprovação do orçamento, inclusive com filtro de data.
- Orçamento conservador separado da estimativa: máximos por contador de resposta Claude
  e por sessão Codex, com limite superior de tokens e tempo visível no relatório.
  Registros incompletos ou ilegíveis impedem aprovação; aliases `cost` e `--check-budget`.
- Campo ausente numa atualização Claude preserva o contador conhecido; OpenAI e Codex
  preservam cache conhecido quando a entrada é desconhecida, sem ocultar excesso de orçamento.
- Comando `cost` com métricas locais de Claude Code, Codex, Antigravity e `run`,
  agrupadas por task, agente, modelo ou papel, em texto, JSON ou Markdown por lote.
- Registro de uso e duração de `run`, incluindo `--task`, cache e custo informado pelo
  provedor, sem guardar prompts ou chaves; falhas na gravação emitem aviso.
- Tarifas configuráveis em `config/precos.json` e verificação de orçamento por task com
  leitor do subconjunto YAML do projeto, sem dependências externas.
- Tokens desconhecidos e limitações dos formatos locais são explicitados, sem estimativas
  de preço; OpenCode/Kilo ainda não têm leitor.
- Orçamento inclui worktrees do mesmo repositório sem incluir outros projetos; troca de
  modelo no Codex distribui diferenças dos acumulados para calcular o custo por modelo.
- Telemetria opcional malformada emite aviso e preserva a resposta de `run`;
  o leitor YAML aceita apóstrofos em strings sem aspas, como `D'Avila`.
- Regressões do acumulado Codex preservam o consumo comprovado como limite inferior,
  mantendo a detecção de orçamento excedido, a indicação de uso parcial e o custo desconhecido.
- Sessões Codex retomadas separam consumo e intervalos por modelo, pasta, branch e papel,
  evitando atribuir o uso de várias tasks à primeira delas.
- O leitor YAML preserva espaços e dois-pontos nos valores e rejeita separadores estruturais
  em strings sem aspas com indicação da linha.
- O filtro `cost --since` considera o término das chamadas de `run`, preservando
  todo o consumo e o excesso de orçamento quando a duração atravessa a data do filtro.
- A deduplicação do Claude conserva o uso atualizado de cada resposta, incluindo cache,
  sem somar parciais repetidas nem ocultar excesso de orçamento.
- Respostas Claude com contadores desconhecidos preservam os subtotais comprovados de
  entrada, saída e cache, com medição parcial e custo desconhecido, sem ocultar orçamento excedido.
- Atualizações parciais da mesma resposta Claude preservam o último valor conhecido de cada
  contador; cópias fora de ordem não apagam consumo comprovado nem duplicam tokens.
- Entrada Anthropic desconhecida mantém cache conhecido no total mínimo de tokens;
  a indicação de medição parcial e custo desconhecido acompanha o registro e o orçamento.

## [0.1.2] - 2026-11-17

Primeira versão publicada.

- CLI `kit.py` com `list`, `validate`, `install`, `new-skill` e `run`, usando apenas
  a biblioteca padrão do Python 3.10+.
- Skills `iniciar-agents-md`, `planejar`, `verificar`, `revisar` e `criar-skill`, no padrão Agent Skills.
- Processo de trabalho, padrões técnicos por área e modelos de task e CI.
- Instalação de skills, instruções e servidores MCP para Claude Code, Codex, Antigravity,
  Cursor, Copilot, Gemini CLI, OpenCode e agentes compatíveis com `.agents/`.
- Configuração MCP global para Codex e Antigravity, com execução mediante confirmação;
  simulação de instalação e proteção dos arquivos do projeto.
- Configuração por projeto em `.kit-ia/projeto.yaml` e versão instalada em `.kit-ia/VERSAO`.
- Execução de skills por API com os protocolos `openai` e `anthropic`.
- Validação de skills, links relativos e configurações; testes com provedor falso e CI no GitHub Actions.
