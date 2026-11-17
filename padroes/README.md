# Padrões técnicos

O que é bom código, por área. Leia só a área da demanda: `projeto.areas` no `projeto.yaml`
diz quais valem no projeto.

As regras do projeto (`AGENTS.md`) vencem estas. Exemplo: um projeto que não usa migrations
continua não usando.

| Arquivo | Área |
|---|---|
| [codigo.md](codigo.md) | Todas: idioma, comentários, nomes, edição |
| [arquitetura-api.md](arquitetura-api.md) | Backend: camadas, DTO, erros, REST, banco |
| [testes.md](testes.md) | Todas: pirâmide, mocks, testes de ponta a ponta |
| [observabilidade.md](observabilidade.md) | Backend e infra: métricas, logs, painéis |
| [seguranca.md](seguranca.md) | Todas |
| [mensageria.md](mensageria.md) | Filas e eventos |
| [integracao-http.md](integracao-http.md) | Chamadas a serviços externos |
| [infra-docker.md](infra-docker.md) | Docker Compose, imagens, CI |
| [performance.md](performance.md) | Carga, gargalos, otimização |
| [frontend-e-design.md](frontend-e-design.md) | Páginas, componentes, protótipos, design |
| [ia-no-desenvolvimento.md](ia-no-desenvolvimento.md) | Uso de agentes, skills, MCP e servidores MCP próprios |
