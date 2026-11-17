# Infraestrutura e Docker

## Docker Compose

- `name:` explícito no compose, para não misturar volumes entre projetos.
- **Imagens com versão fixa** (`postgres:16-alpine`, `rabbitmq:3.13-management-alpine`); nunca `latest`.
- **Healthcheck em todo serviço de infraestrutura**, e dependência condicionada:
  ```yaml
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U app -d app"]
    interval: 5s
    timeout: 5s
    retries: 5
  depends_on:
    postgres: { condition: service_healthy }
  ```
- Uma porta de host por projeto, para dois projetos subirem juntos.
- Volumes nomeados; `down` mantém os dados, `down -v` apaga.
- **Perfis para o que é opcional:** `app`, `testes`, `ui`, `carga`, `ia`.
- Configuração por variável de ambiente com padrão (`${CARGA_TAXA:-200}`).
- Arquivos de configuração montados somente para leitura (`:ro`); provisioning (Grafana,
  RabbitMQ) por arquivo versionado.
- **O README permite subir tudo a partir de um clone limpo.**

## Imagens, CI e deploy

- Dockerfile em múltiplos estágios (build e execução separados), imagem final enxuta, usuário
  sem privilégio de root.
- Pipeline de CI que roda os gates de integração e bloqueia o merge se falharem.
- Deploy automatizado só a partir da branch principal (ou de homologação), com aprovação
  manual para produção.
- Infraestrutura descrita em código (Terraform, Bicep, Pulumi) quando houver nuvem.
- Segredos de produção num cofre (Key Vault, Secrets Manager), nunca em variável de pipeline
  em texto.
- Modelos de CI para os projetos: `.kit-ia/modelos/ci/` (GitHub Actions e Azure Pipelines).
