# <Nome do projeto>

<Uma ou duas frases: o que o sistema faz e para quem.>

Este arquivo é lido pelos agentes de IA (Claude Code, Codex, Cursor, Copilot, Gemini...) no início
de toda sessão. Mantenha curto: só o que vale sempre e o agente não descobre sozinho lendo o código.

## Como trabalhar
- No início de toda sessão, leia `.kit-ia/processo/00-nucleo.md` e `.kit-ia/projeto.yaml`.
  Os demais arquivos de `.kit-ia/processo/` e `.kit-ia/padroes/` só quando a etapa pedir.
- Antes de criar ou editar arquivos, apresente o plano e espere a aprovação explícita do usuário.
  Responder a uma pergunta de esclarecimento não é aprovação.
- As regras deste arquivo vencem as do `.kit-ia/`.

## Stack
- <linguagem e versão, framework, banco, mensageria>
- Testes: <frameworks>

## Como rodar
- Infraestrutura: `<comando>`
- Aplicação: `<comando>` (porta <n>)
- Testes: `<comando>`
- Lint/formatação: `<comando>`

## Arquitetura (não quebrar)
- <regra de camadas. Ex.: Controller não tem regra de negócio; só traduz e chama o Service.>
- <o que nunca sai de uma camada. Ex.: a entidade não sai do Service; para fora, sempre DTO.>
- <banco. Ex.: mudança no banco = nova migration; nunca editar uma migration antiga.>
- Segredos (chaves de API, senhas) só em variável de ambiente ou `.env` fora do Git.

## Convenções
- <idioma do código e dos comentários>
- <padrão de nomes; onde ficam os testes>
- Cada regra nova ganha um teste unitário; cada rota nova, um teste de ponta a ponta.

## Antes de dizer "pronto"
- `<comando de testes>` passando.
- <verificação real: rota, tela ou comando que prova que funciona>
- Use a skill `verificar`; antes do commit, a skill `revisar`.
