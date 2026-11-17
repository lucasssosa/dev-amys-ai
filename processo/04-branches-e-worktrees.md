# Branches e worktrees

## 1. O modelo

```text
task/BL-LU-12-hero  (worktree) ─┐
task/BL-LU-13-form  (worktree) ─┼─ integração ─> release/<nome> ─ promoção ─> [homologacao] ─ promoção ─> main
task/BL-LU-14-seo   (worktree) ─┘                 ▲ integrador-arquiteto
                                                  │ uma task por vez, gate 2 a cada uma
hotfix/BL-LU-20-... (sai da principal) ─────────────────────────────────────────────> main
                                                  └── e volta para a release em andamento
```

- **Branch por task**, nunca por frente ou sprint. Mudar prioridade não exige renomear nada.
- **O checkout principal nunca troca de branch.** Cada task vive na própria worktree.
- **Integração** junta tasks na release. **Promoção** leva a release inteira, já testada,
  ao próximo destino. Os destinos vêm de `branches.destinos` no `projeto.yaml`
  (ex.: `[main]` ou `[homologacao, main]`).
- Os nomes seguem os modelos de `branches` no `projeto.yaml`, para casar com a convenção de
  cada empresa (ex.: `feature/{data}-{chamado}-{slug}`).

## 2. Modos de worktree

`worktrees.modo` no `projeto.yaml`:

| Modo | Quando usar | Custo |
|---|---|---|
| `por_task` (padrão) | Tasks em paralelo, várias sessões ou devs | Disco e setup por worktree (ex.: `npm ci`) |
| `por_lote` | Tasks pequenas em sequência, uma sessão | Uma worktree para o lote inteiro |
| `nenhum` | Projeto pequeno, uma task por vez | Zero; paralelismo proibido |

Criar uma worktree custa **zero token**: é um comando Git. O que gasta token é o contexto de
cada agente, com ou sem worktree. O custo real é disco e tempo de setup: dependências de
frontend são instaladas por worktree; o cache do Maven (`~/.m2`) é compartilhado.

Recursos disputados entre worktrees: portas (`ng serve`, API), banco local e builds pesados.
Use portas aleatórias (Testcontainers) ou a faixa de portas do `projeto.yaml`; nunca dois builds
completos do mesmo módulo ao mesmo tempo.

(ainda não implementado) `kit.py task pegar <ID>` cria a branch e a worktree em `worktrees.pasta` e roda
`worktrees.setup`.

## 3. Integração e conflitos

O integrador pega as tasks `entregue` de uma fila, **uma por vez**, na ordem de entrega:

1. Atualiza a release e faz o merge da branch da task.
2. Se houver conflito, classifica:
   - **Mecânico:** as duas tasks mexeram perto, sem disputar a mesma lógica (imports, itens
     de lista, rotas acrescentadas, lockfile a regerar). **O integrador resolve.**
   - **Semântico:** as duas tasks mudaram a mesma lógica, ou o merge passou sem conflito
     textual mas o gate 2 falhou. **A task volta (`devolvida`)** para o executor, com o motivo
     e os arquivos. Se as duas intenções forem incompatíveis, a decisão é do usuário.
3. Confere a arquitetura: o diff respeita as regras de `AGENTS.md` e os padrões da área?
   Violação também devolve a task.
4. Roda o gate 2. Verde: `integrada`. Vermelho: `devolvida`.

Motivo da regra semântica: resolver lógica conflitante "no chute" produz bug silencioso que
compila e parece certo. Quem sabe a intenção é quem escreveu.

(ainda não implementado) `kit.py integrar` processa a fila.

## 4. Promoção

1. Gate 3 da release ([05-gates.md](05-gates.md)).
2. Merge da release no próximo destino. Para a branch principal, só com ok do usuário.
3. Se houver hospedagem, a promoção pode ser um pull request (`hospedagem.abrir_pr`).
4. A release promovida vira **tag** (ex.: `release-2026-11-20`) antes de ser apagada.

(ainda não implementado) `kit.py promover <destino>`.

## 5. Hotfix

Urgência em produção:

1. Branch `hotfix/<ID>-<slug>` a partir da principal, em worktree própria.
2. Gate 1 e gate 3 (o hotfix vai direto para produção).
3. Promoção para a principal com ok do usuário.
4. **Volta para a release em andamento** (merge da principal na release), para ela não perder a
   correção.

## 6. Limpeza

(ainda não implementado) `kit.py limpar`:

- remove worktrees de tasks `integrada`, `promovida` ou `descartada`;
- apaga branches locais de task já integradas (o Git recusa apagar o que não foi integrado, e o
  kit não força);
- remove registros de worktrees cujas pastas sumiram (`git worktree prune`);
- compacta logs antigos.

Proteções: nunca remove worktree com mudança sem commit nem branch com commit não integrado;
nunca apaga branch no remoto sem perguntar. O padrão é **mostrar a lista e pedir confirmação**;
com `limpeza.modo: apos_promocao`, roda sozinho depois de cada promoção.

(ainda não implementado) `kit.py task descartar <ID>`: remove worktree e branch de uma task abandonada, com
confirmação.

## 7. Comandos manuais

```bash
git worktree add ../<repo>-wt/BL-LU-12 -b task/BL-LU-12-hero release/<nome>
git worktree list
git -C ../<repo>-wt/BL-LU-12 status
git worktree remove ../<repo>-wt/BL-LU-12      # recusa se houver mudança sem commit
git branch -d task/BL-LU-12-hero               # recusa se não foi integrada
git worktree prune
```

## 8. Estado compartilhado

O estado das tasks (backlog, quem pegou o quê, eventos) precisa ficar num **lugar só**:

- **Entre worktrees:** se o estado ficasse dentro do código, cada worktree teria uma cópia e
  uma não enxergaria a outra.
- **Entre devs (ainda não implementado):** o estado vive numa **branch própria** no remoto do projeto
  (ex.: `dev-amys-ai/estado`), sem código, com um arquivo por task. No início de cada sessão,
  um script sincroniza essa branch e entrega ao agente um índice curto, sem gastar token de
  modelo. Funciona em qualquer provedor, porque é Git puro.

Cada evento registra data, autor, task, transição e hash. (ainda não implementado) Formato e local definitivos.
