# Git

## Commits

- Nunca adicione IA como coautor ou contribuidor: sem `Co-Authored-By` de agente ou modelo, sem 'Generated with' em pull requests.

- **Um commit por task** (ou um por fase, se a task tiver fases declaradas).
- **Commit com pathspec:** `git commit -m "..." -- <arquivos da task>`. Com `nenhum` ou
  `por_lote`, o índice é compartilhado entre sessões; `git add .`, `git add -A` e
  `git commit -a` levam junto o trabalho de outra sessão. Use pathspec também em worktree
  própria: é o hábito que evita o acidente.
- **Antes do commit:** `git diff --stat -- <arquivos>`. Arquivo editado que não aparece
  significa que o trabalho não está no disco.
- **Nunca `reset`**, nem no próprio commit local. Commit errado: pare e relate com o hash.
- **Commite sem perguntar, mas sempre avise.** Push e promoção para a principal: só com ok.
- **Nunca commite:** segredos, `.env`, configuração local de máquina, arquivos de IDE.
  O `.env.exemplo` (sem valores reais) é versionado.

## Mensagem

Conventional Commits, em português:

```text
feat(cadastro): impede inscrição duplicada com o mesmo e-mail

O formulário aceitava o mesmo e-mail duas vezes quando o usuário clicava rápido.

Task: BL-LU-12
```

- Tipos: `feat`, `fix`, `refactor`, `test`, `docs`, `style`, `perf`, `build`, `ci`, `chore`.
- O título diz o **efeito**, não o mecanismo: "impede inscrição duplicada", não
  "adiciona if no service".
- Proibido: "ajustes gerais", "diversas melhorias", "correções".
- Trailer `Task: <ID>` em todo commit de task.
- Se o projeto exige outro padrão (ex.: número do chamado), ele vence: está no `AGENTS.md`.

## Branches remotas e pull requests

- Os comandos de pull request dependem do provedor do projeto (`hospedagem` no
  `projeto.yaml`: GitHub, Azure DevOps, GitLab ou nenhum).
- Branch de task no remoto também é um sinal para outros devs: "esta task está em andamento"
  ([04-branches-e-worktrees.md](04-branches-e-worktrees.md)).
- Nunca force push em branch compartilhada (release, homologação, principal).

## Finais de linha

Projetos com arquivos CRLF geram diffs enganosos. Antes de investigar um diff gigante, rode
`git diff --ignore-cr-at-eol --stat`. Projeto novo: use `.gitattributes` com `* text=auto eol=lf`.
