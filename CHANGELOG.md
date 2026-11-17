# Changelog

## [0.2.0] - 2026-11-17

- Comando `custo` com métricas locais de Claude Code, Codex, Antigravity e `executar`,
  agrupadas por task, agente, modelo ou papel, em texto, JSON ou Markdown por lote.
- Registro de uso e duração de `executar`, incluindo `--task`, cache e custo informado pelo
  provedor, sem guardar prompts ou chaves; falhas na gravação emitem aviso.
- Tarifas configuráveis em `config/precos.json` e verificação de orçamento por task com
  leitor do subconjunto YAML do projeto, sem dependências externas.
- Tokens desconhecidos e limitações dos formatos locais são explicitados, sem estimativas
  de preço; OpenCode/Kilo ainda não têm leitor.
- Orçamento inclui worktrees do mesmo repositório sem incluir outros projetos; troca de
  modelo no Codex distribui diferenças dos acumulados para calcular o custo por modelo.
- Telemetria opcional malformada emite aviso e preserva a resposta de `executar`;
  o leitor YAML aceita apóstrofos em strings sem aspas, como `D'Avila`.
- Regressões do acumulado Codex preservam o consumo comprovado como limite inferior,
  mantendo a detecção de orçamento excedido, a indicação de uso parcial e o custo desconhecido.
- Sessões Codex retomadas separam consumo e intervalos por modelo, pasta, branch e papel,
  evitando atribuir o uso de várias tasks à primeira delas.
- O leitor YAML preserva espaços e dois-pontos nos valores e rejeita separadores estruturais
  em strings sem aspas com indicação da linha.

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
