# Fluxo de uma demanda

## 1. Classificar o pedido

| Tipo | Exemplo | O que fazer |
|---|---|---|
| **Informativo** | "Como funciona o cálculo do frete?" | Responder. Não gera registro. |
| **Ajuste rápido** | O usuário manda pular o processo para trocar um texto | Editar direto, sem task, sem gate. Avisar o que mudou. |
| **Task normal** | "Adicionar filtro por categoria na listagem" | Seguir as etapas abaixo. |
| **Task de risco** | Regra de negócio, dados, segurança, efeito externo, infraestrutura de produção | Etapas abaixo, com revisor obrigatório. |

Na dúvida entre normal e risco, trate como risco.

## 2. Etapas

1. **Registrar.** Todo pedido que não é informativo vira item de backlog, numa frente
   (seção 4). (ainda não implementado: `kit.py task criar`.)
2. **Descobrir.** Somente leitura: código, `AGENTS.md`, padrões da área. Leitura leve o
   coordenador faz; leitura extensa vai para um leitor ([02-papeis-e-despacho.md](02-papeis-e-despacho.md)).
3. **Planejar.** Objetivo, critério de pronto, abordagem e alternativas descartadas, tasks e
   arquivos de cada uma, o que roda em paralelo, subagentes e scripts que serão disparados,
   gates que vão rodar, orçamento estimado, riscos e o que fica fora do escopo.
4. **Aprovação.** Pare e espere o ok explícito do usuário.
5. **Escrever as tasks** no formato de [03-tasks.md](03-tasks.md). Estado: `pronta`.
6. **Executar.** O executor pega a task, trabalha na worktree dela, passa no gate 1 e
   commita ([04-branches-e-worktrees.md](04-branches-e-worktrees.md), [05-gates.md](05-gates.md)).
7. **Revisar.** Obrigatório em task de risco ou quando o usuário pedir.
8. **Integrar.** O integrador junta a task na release e roda o gate 2.
9. **Promover.** A release passa no gate 3 e sobe para o próximo destino
   (homologação, se houver, e depois a principal). Para a principal, sempre com ok do usuário.
10. **Fechar.** Relatório do lote com custo e tempo ([07-custo-e-tempo.md](07-custo-e-tempo.md)),
    limpeza de worktrees e branches temporárias.

Trabalhe em **lotes de 3 a 6 tasks**. Fechado o lote, registre o estado e encerre a sessão:
sessões longas acumulam contexto e ficam caras.

## 3. Estados de uma task

| Estado | Significa | Quem move |
|---|---|---|
| `backlog` | Registrada, sem task escrita | Coordenador |
| `pronta` | Task escrita e completa; pode ser pega | Coordenador |
| `em_andamento` | Um executor pegou; a worktree existe | Executor |
| `entregue` | Commit feito, gate 1 verde | Executor |
| `em_integracao` | O integrador está juntando na release | Integrador |
| `integrada` | Está na release, gate 2 verde | Integrador |
| `devolvida` | Conflito semântico ou gate 2 vermelho: volta ao executor com o motivo | Integrador |
| `promovida` | Chegou ao destino final | Coordenador, com ok do usuário |
| `descartada` | Abandonada; worktree e branch removidas | Usuário |

Uma task só tem **um** estado e **um** dono por vez. (ainda não implementado: as transições são feitas só pelo
`kit.py task`, que recusa transição inválida.)

## 4. Frentes (padrão) e sprints (opção)

O trabalho é agrupado por **frente**: um objetivo, sem prazo fixo (`landing-v1`,
`ux-promocoes`, `suporte`). Várias frentes podem estar ativas ao mesmo tempo. Uma frente
termina quando o objetivo é atingido.

Se o projeto precisa de prazo combinado, use `planejamento.modo: sprints` no `projeto.yaml`:
a sprint tem data de início e fim e escopo fechado no início.

Em nenhum dos dois casos a frente ou a sprint vira branch: a branch é por task
([04-branches-e-worktrees.md](04-branches-e-worktrees.md)).

## 5. Interrupções

Chegou algo novo no meio do trabalho:

- **Urgente em produção:** caminho de hotfix ([04-branches-e-worktrees.md](04-branches-e-worktrees.md)).
- **Não urgente:** vira item de backlog na frente certa (ou em `avulsas`) e entra no próximo lote.
- **Nunca** troque a branch do checkout principal nem mexa na worktree de outra task para
  atender a interrupção.
