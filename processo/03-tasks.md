# Tasks

Uma task é a única coisa que o executor lê para trabalhar. Se ela não basta sozinha, o
executor vai explorar o projeto, e isso gasta tokens e produz escopo inventado.

## Identificador

- `BL-<sigla do dev>-<número>`, por exemplo `BL-LU-12`. A sigla vem de
  `planejamento.id_prefixo` no `projeto.yaml` e evita que dois devs gerem o mesmo número.
- Se o projeto usa um rastreador (Azure Boards, GitHub Issues), o ID do rastreador pode
  substituir o número: `BL-4512`.
- O ID nunca muda, mesmo que a task troque de frente ou de prioridade.

## Formato

Modelo pronto: [../modelos/tarefa.md](../modelos/tarefa.md). Tamanho alvo: 3 a 5 KB.

| Campo | Obrigatório | Para quê |
|---|---|---|
| Cabeçalho: ID, frente, tipo, risco, autor, selo de revisão | Sim | O tipo escolhe os gates; o risco decide se tem revisor; o selo diz qual versão o executor leu |
| Objetivo | Sim | Uma frase |
| Entregável para o usuário | Sim | O que ele vai ver ou poder fazer. Sem isto, a task não é despachada |
| O que esta task não faz | Sim | Fecha o escopo |
| Arquivos que esta task possui | Sim | Define o paralelismo e o que o commit pode conter |
| Padrões a seguir | Sim | Lista de `.kit-ia/padroes/<área>.md` que o executor lê antes de editar |
| Pode rodar em paralelo com | Sim | IDs ou "nenhuma" |
| Critérios de aceite | Sim | Asserções verificáveis, não desejos |
| Prova de vida | Sim | O comando ou a chamada que mostra funcionando |
| O que não fazer | Quando houver | Armadilhas conhecidas daquela área |
| Resultado | Na entrega | Hash, evidência, limitações |

Tipos de task: os mesmos nomes de `gates.por_tipo` do `projeto.yaml` (ex.: `backend`,
`frontend`, `design`, `infra`, `seguranca`, `performance`, `docs`).

## Regras de escrita

- Não escreva número, contagem, nome de coluna ou de arquivo que você não verificou nesta
  sessão ([08-armadilhas.md](08-armadilhas.md)).
- Critério de aceite com contagem diz também o que precisa sobreviver:
  "zero `console.log`, **e** nenhum teste removido".
- Não reabra decisão que o usuário já fechou; cite-a.
- O coordenador preenche **Padrões a seguir** a partir de `projeto.areas` no `projeto.yaml`
  e do tipo da task, consultando o índice dos padrões. Liste os arquivos aplicáveis; se não
  houver nenhum, escreva "nenhum" com o motivo. O executor lê a lista antes de editar.
- Task alterada depois de despachada sobe o selo: `Revisão 2 — <data hora>`.

## Onde as tasks ficam

A centralização automática ainda não foi implementada. Use a pasta que o usuário indicar,
com um arquivo por task, e mantenha-a fora do Git do código. O estado deve ser compartilhado
entre worktrees e devs ([04-branches-e-worktrees.md](04-branches-e-worktrees.md), seção 8).
