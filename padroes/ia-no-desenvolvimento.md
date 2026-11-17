# IA no desenvolvimento

## As peças

| Peça | O que é | Regra |
|---|---|---|
| `AGENTS.md` (ou `CLAUDE.md`) | Manual lido em toda sessão | Curto e atual: só o que vale sempre e não se deduz do código |
| Skill | Receita carregada sob demanda | Passos numerados e verificáveis; termina pedindo evidência |
| MCP | Acesso a outro sistema | Menor privilégio; leitura liberada, escrita confirmada |
| Hook | Comando que roda sempre num evento | O que **tem** de acontecer não pode depender do modelo lembrar |
| Permissões | O que roda sem perguntar | Libere testes e leitura; escrita e efeito externo pedem confirmação |

"Conselho vai no `AGENTS.md`. Receita vira skill. Acesso a sistema é MCP. O que tem que
acontecer é hook."

## O workflow em 8 etapas

| Etapa | No kit |
|---|---|
| 1. Entender | Skill `iniciar-agents-md`; descoberta somente leitura |
| 2. Projetar | Skill `planejar` (opções e escolha) |
| 3. Planejar testes | Skill `planejar` (casos de erro e de limite) |
| 4. Implementar | Plano aprovado; documentação atual (Context7); passos pequenos |
| 5. Verificar | Skill `verificar`; gates ([processo/05-gates.md](../processo/05-gates.md)) |
| 6. Revisar | Skill `revisar` |
| 7. Entregar | Commit no padrão ([processo/06-git.md](../processo/06-git.md)), README atualizado |
| 8. Operar | Causa, não só sintoma; métricas e logs |

"Você decide e aprova em cada seta." "O código é seu: você responde por ele."

## Boas práticas

Dê contexto; peça o plano antes do código; passos pequenos; exija evidência; leia o diff;
use documentação atual; não cole segredos; peça o porquê das decisões.

## Servidor MCP próprio

- A ferramenta MCP é um "Controller para a IA": sem regra de negócio, chama o mesmo Service
  do REST.
- **A descrição é para a IA:** o que faz, quando usar, formato de cada campo.
- **Toda porta de entrada valida:** sem `@Valid`, chame o validador à mão.
- **Erro é mensagem:** devolva `isError: true` com texto claro, para a IA corrigir sozinha.
- Nome em snake_case; anotações corretas (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`).
- Cada ferramenta nova ganha teste unitário e E2E com o cliente MCP oficial.
