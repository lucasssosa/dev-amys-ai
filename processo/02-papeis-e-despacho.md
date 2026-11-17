# Papéis e despacho

O recurso escasso é o **contexto do coordenador**, não o token do executor. Cada papel existe
para que o coordenador leia pouco e decida bem.

## Papéis

| Papel | Faz | Não faz |
|---|---|---|
| **Coordenador** (sessão principal) | Entende o pedido, registra, planeja, escreve a task, despacha, lê o diff, relata | Código de feature, nem "só uma linha"; ler log bruto ou imagem |
| **Executor** | Uma task por vez, na worktree dela: lê os padrões listados na task antes de editar, consulta APIs externas no Context7 (ou outro MCP de documentação; sem ele, documentação ou código da versão instalada), faz edição pontual, gate 1 e commit | Decidir escopo, consertar código alheio, push, mexer em outra worktree |
| **Integrador-arquiteto** | Junta tasks entregues na release, uma por vez; confere se o código respeita a arquitetura do projeto; resolve conflito mecânico; roda o gate 2 | Resolver conflito semântico; reescrever a task |
| **Revisor** | Mede e relata em tasks de risco | Escrever ou corrigir código |
| **Leitor** | Lê logs, capturas de tela ou muitos arquivos e devolve resumo de até 1 KB | Decidir |
| **Usuário** | Decide produto e escopo; aprova planos e promoções; faz a validação visual | |

Quem escreveu o código não o revisa nem o integra: são sessões ou subagentes diferentes.
Os contratos completos de cada papel ainda não foram implementados; valem as regras deste arquivo.

## Despacho

- **Prompt enxuto.** "Execute a task `<ID>`. Task: `<caminho da task>`. Siga
  `.kit-ia/processo/02-papeis-e-despacho.md` (papel executor). Leia os padrões listados na task
  antes de editar. Para APIs externas, consulte a documentação da versão usada pelo Context7
  (ou outro MCP de documentação); sem ele, leia a documentação ou o código da versão instalada.
  Nunca escreva de memória. A task aprovada ou devolvida pelo revisor é o plano aprovado:
  execute sem pedir nova aprovação." Acrescente só o que for
  específico deste despacho. A task é autossuficiente; não repita o contexto no prompt.
- **Retorno do executor (até 2 KB), nesta ordem:** revisão da task que leu, hash do commit,
  evidência do gate 1, validação simulada ou real, limitações, achados que pedem decisão.
- **Retorno do integrador:** para cada task, `integrada` (hash do merge, gate 2) ou
  `devolvida` (motivo, arquivos, o que o executor precisa decidir).
- **Retorno do revisor:** Parte A, PASS ou FAIL com o número medido; Parte B, mudanças em
  testes (mudança de valor esperado é o achado mais grave); Parte C, o que a task não previa;
  veredito: aprovar, aprovar com dívida ou não aprovar.
- **Leia o diff, não aceite o relatório.** O retorno de um subagente é uma alegação.
- **Antes de redespachar,** confira se o agente anterior ainda está vivo.

## Paralelismo

Duas tasks rodam em paralelo se, e somente se, as listas "Arquivos que esta task possui" não
se cruzam. Com worktrees separadas, o Git deixa de colidir, mas os recursos não:
portas, bancos locais e builds pesados continuam disputados
([04-branches-e-worktrees.md](04-branches-e-worktrees.md)).

## Script ou subagente?

| Use script quando | Use subagente quando |
|---|---|
| A tarefa é repetitiva e determinística: carga, varredura de segurança, capturas de tela, coleta de métricas, testes | A tarefa exige julgamento: escrever código, revisar, investigar causa |

O script grava a saída completa em arquivo e imprime um resumo curto. Script não gasta token
de modelo; ler a saída inteira dele gasta, por isso o resumo.

## Modelos

O `projeto.yaml` diz qual modelo cada papel usa (`modelos`). Regra geral: o modelo mais barato
que resolve. Modelo mais caro que o configurado, só com ok do usuário naquela tarefa.
