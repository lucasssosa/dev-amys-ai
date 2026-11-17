---
name: iniciar-agents-md
description: Cria ou atualiza o AGENTS.md de um projeto (o manual que todo agente de IA lê no início da sessão) e preenche o .kit-ia/projeto.yaml a partir do código real, com stack, comandos verificados, regras de arquitetura e o que conferir antes de dizer pronto. Use ao começar a usar IA num projeto, quando o AGENTS.md estiver vazio ou desatualizado, ou quando o usuário pedir "preencher o AGENTS.md", "documentar o projeto para a IA" ou "init".
---

# Iniciar o AGENTS.md

Objetivo: um `AGENTS.md` curto, verdadeiro e útil, que qualquer agente leia e já trabalhe do jeito do projeto.

## Passos

1. **Ler o que já existe.** `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`, `.cursor/rules/`,
   `.github/copilot-instructions.md`, README. O que for válido é consolidado no `AGENTS.md`.
2. **Descobrir a stack.** Arquivos de build e dependências, `docker-compose.yml`, `Dockerfile`, CI.
   Anote linguagem e versão, framework, banco, mensageria e frameworks de teste.
3. **Descobrir os comandos e testá-los.** Infraestrutura, aplicação, testes, lint.
   Rode os que forem rápidos e seguros (build, testes) para confirmar que funcionam.
   O que não puder confirmar, marque com `(confirmar)`.
4. **Deduzir a arquitetura do código.** Camadas e o que cada uma pode fazer, o que nunca cruza uma
   camada, como o banco evolui (migrations), onde ficam os testes. Só escreva regra que o código
   realmente segue, ou que o usuário confirmar.
5. **Escrever** seguindo `modelo-AGENTS.md` (nesta pasta), com as seções:
   Como trabalhar, Stack, Como rodar, Arquitetura (não quebrar), Convenções, Antes de dizer "pronto".
   A seção "Como trabalhar" é copiada do modelo como está: ela liga o projeto ao processo do kit.
6. **Preencher o `.kit-ia/projeto.yaml`**, se existir: `projeto.areas`, `branches` (confira a
   branch principal e se há homologação com `git branch -a`), `hospedagem.provedor` (pelo
   `git remote -v`) e `comandos`, com os mesmos comandos verificados no passo 3.
   Comando não confirmado fica vazio, nunca inventado.
7. **Integrar com os agentes.** Se existir `CLAUDE.md` com conteúdo, proponha mover o conteúdo para o
   `AGENTS.md` e deixar no `CLAUDE.md` só a linha `@AGENTS.md` (mais o que for exclusivo do Claude Code).
8. **Mostrar e perguntar.** Apresente os arquivos e liste os itens `(confirmar)` para o usuário decidir.

## Regras de conteúdo
- Curto: até ~100 linhas. Só o que vale **sempre** e que o agente **não descobre** lendo o código.
- Comandos exatos e copiáveis, não descrições.
- Regras escritas como ordens verificáveis ("Controller não acessa o Repository"),
  não como desejos ("manter o código limpo").
- Nada de listar todos os arquivos ou repetir o README.
- Nada de segredos: só os nomes das variáveis de ambiente.

## Não fazer
- Inventar comando ou regra que não foi visto no projeto.
- Apagar instruções existentes sem perguntar.
