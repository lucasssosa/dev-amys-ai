---
name: criar-skill
description: Cria uma skill nova no padrão aberto Agent Skills (SKILL.md), portável entre agentes e modelos. Decide se o caso é mesmo uma skill, escreve uma descrição que ativa no momento certo e instruções verificáveis. Use quando o usuário quiser transformar um procedimento repetido em skill, ou pedir "criar skill", "nova skill" ou "automatizar este passo a passo".
---

# Criar uma skill

Objetivo: uma skill que qualquer agente (Claude Code, Codex, Cursor, Copilot, Gemini, OpenCode) e
qualquer modelo consegue seguir, e que é ativada só quando deve.

## 1. É mesmo uma skill?

| O que você tem | Onde colocar |
|---|---|
| Regra que vale **sempre** (arquitetura, convenção) | `AGENTS.md` |
| **Procedimento** repetido, com passos (revisar, liberar versão, criar endpoint) | **skill** |
| Acesso a **outro sistema** (banco, Jira, API) | servidor **MCP** |
| Algo que precisa rodar **sempre** num evento, sem depender do modelo | hook / script / CI |

## 2. Entender o procedimento
Pergunte (ou deduza): quando ele acontece, o que recebe, o que entrega, como saber que deu certo,
e quais erros já aconteceram ao fazê-lo à mão.

## 3. Escrever

- **Pasta e nome:** `skills/<nome>/SKILL.md`; nome em kebab-case, igual ao `name:` do frontmatter, até 64 caracteres.
- **Frontmatter:** só `name` e `description` (os campos do padrão). Campos de um agente específico
  quebram a portabilidade.
- **Descrição** (até 1024 caracteres, uma linha): *o que faz* + *quando usar*, com as palavras que
  o usuário diria ("Use quando ... ou quando o usuário pedir \"...\"").
  É só ela que o agente lê para decidir se carrega a skill.
- **Corpo:** Objetivo (uma frase) → Antes de começar → Passos numerados → Formato da resposta → Não fazer.
- **Cada passo é uma ação verificável** ("rode os testes e mostre a contagem"), não um conselho ("teste bem").

## 4. Regras de portabilidade
- Descreva **ações**, não ferramentas de um agente: "leia o arquivo", "rode o comando",
  nunca "use a ferramenta Read/Bash".
- Arquivos de apoio ficam **dentro da pasta da skill** e são citados por caminho relativo
  (`referencias/guia.md`, `scripts/gerar.py`); nunca por caminho absoluto ou de um agente
  (`~/.claude/...`).
- O `SKILL.md` deve ser curto (idealmente até ~200 linhas). Detalhes longos vão em `referencias/`,
  e o agente só os lê quando o passo pede (carregamento progressivo).
- Scripts de apoio: sem dependências exóticas, funcionando no Windows, Linux e Mac.
- Nada de segredos na skill.

## 5. Validar
- No repositório do kit: `python kit.py nova-skill <nome> --descricao "..."` cria o esqueleto;
  depois `python kit.py validar`.
- Teste em pelo menos **dois agentes ou modelos**: faça um pedido que deveria ativar a skill e um que
  não deveria. Se não ativar, melhore a descrição; se ativar demais, deixe-a mais específica.
- Para testar a skill num modelo sem agente: `python kit.py executar <nome> --entrada "..."`.

## Não fazer
- Skill que repete o que o modelo já faz bem sem instrução.
- Várias tarefas numa skill só: uma skill, um procedimento.
