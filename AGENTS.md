# dev-amys-ai

Kit de IA para engenharia de soluções digitais, agnóstico de modelo e de agente. Uma única fonte
de skills, processo, padrões técnicos e servidores MCP, instalada em qualquer projeto com `kit.py`.
Explique o porquê das decisões técnicas.

## Como trabalhar
- No início de toda sessão, leia [processo/00-nucleo.md](processo/00-nucleo.md). Neste repositório
  o processo está na fonte (`processo/`, `padroes/`), não em `.kit-ia/`.
- Antes de criar ou editar arquivos, apresente o plano e espere a aprovação explícita do usuário.
  Responder a uma pergunta de esclarecimento não é aprovação.
- Cada entrega começa com um plano aprovado e termina com testes, `validate`, instalação
  de teste e uma versão.

## Stack
- Python 3.10+ **só com a biblioteca padrão** (sem dependências: o kit roda em qualquer máquina e em CI).
- Testes: `unittest` da biblioteca padrão. CI: GitHub Actions.

## Como rodar
- Listar: `python kit.py list`
- Validar skills, links da documentação e config: `python kit.py validate`
- Instalar num projeto: `python kit.py install <pasta> [--agents claude,universal] [--dry-run]`
- Desinstalar de um projeto: `python kit.py uninstall <pasta> [--dry-run] [--yes]`
- Executar uma skill num modelo: `git diff | python kit.py run revisar` (config no `.env`)
- Medir uso: `python kit.py cost --since 2026-11-16 --by agent` (ou `--json`, `--batch ID,ID`)
- Conferir orçamento: `python kit.py cost --check-budget <pasta do projeto>`
- Testes: `python -m unittest discover -s tests -v`

## Arquitetura (não quebrar)
- `skills/`, `processo/`, `padroes/` e `modelos/` são a fonte da verdade. As cópias nos projetos
  (`.claude/skills/`, `.agents/skills/`, `.kit-ia/`) são geradas pelo `kit.py install`: nunca editar a cópia.
- `.kit-ia/projeto.yaml` é do projeto: o kit cria se não existir e nunca sobrescreve.
- Links entre `processo/`, `padroes/` e `modelos/` são relativos e não saem dessas pastas, para
  funcionarem aqui e em `.kit-ia/` (o `validate` confere).
- Skills seguem o padrão Agent Skills: `skills/<nome>/SKILL.md`, frontmatter só com `name`
  (igual à pasta) e `description` (o que faz + quando usar, até 1024 caracteres).
- Skills, processo e padrões são agnósticos: descrevem ações ("rode", "leia o arquivo"), nunca
  ferramentas de um agente específico.
- Caminhos de cada agente ficam em `config/agentes.json`; servidores MCP em `config/mcp.json`.
  O código só traduz; não fixar caminho de agente no código.
- A instalação nunca sobrescreve o que é do usuário sem `--force`: JSON existente é mesclado,
  pasta sem o marcador `.kit-ia` é mantida, AGENTS.md e CLAUDE.md existentes não são tocados.
- Chaves de modelo só no `.env` (fora do Git) ou em variável de ambiente.

## Convenções

- Nunca adicione IA como coautor ou contribuidor: sem `Co-Authored-By` de agente ou modelo, sem 'Generated with' em pull requests.
- Código, nomes, mensagens e comentários em português; comentários didáticos e objetivos,
  explicando o porquê.
- Erro esperado vira `ErroKit` (mensagem clara, código de saída 1), não stack trace.
- Cada comando ou regra nova do `kit.py` ganha teste em `tests/test_kit.py`.
- Chamadas a modelos nos testes usam o servidor falso (`ProvedorFalso`), nunca um provedor real.
- Mudança visível ao usuário entra no `CHANGELOG.md`; a versão fica em `VERSAO` no `kit.py`.
- Commits no padrão de [processo/06-git.md](processo/06-git.md).

## Antes de dizer "pronto"
- `python -m unittest discover -s tests -v` passando.
- `python kit.py validate` sem problemas.
- Se mexeu na instalação: `python kit.py install <pasta temporária>` e conferir os arquivos gerados.
