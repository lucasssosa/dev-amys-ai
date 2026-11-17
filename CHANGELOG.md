# Changelog

## [0.1.2] - 2026-11-17

Primeira versão publicada.

- CLI `kit.py` com `listar`, `validar`, `instalar`, `nova-skill` e `executar`, usando apenas
  a biblioteca padrão do Python 3.10+.
- Skills `iniciar-agents-md`, `planejar`, `verificar`, `revisar` e `criar-skill`, no padrão Agent Skills.
- Processo de trabalho, padrões técnicos por área e modelos de task e CI.
- Instalação de skills, instruções e servidores MCP para Claude Code, Codex, Antigravity,
  Cursor, Copilot, Gemini CLI, OpenCode e agentes compatíveis com `.agents/`.
- Configuração MCP global para Codex e Antigravity, com execução mediante confirmação;
  simulação de instalação e proteção dos arquivos do projeto.
- Configuração por projeto em `.kit-ia/projeto.yaml` e versão instalada em `.kit-ia/VERSAO`.
- Execução de skills por API com os protocolos `openai` e `anthropic`.
- Validação de skills, links relativos e configurações; testes com provedor falso e CI no GitHub Actions.
