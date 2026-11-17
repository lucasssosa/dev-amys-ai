# Observabilidade

Três sinais: **métricas** ("quanto? está piorando?"), **logs** ("o que aconteceu naquela
requisição?") e **traces** ("por onde a requisição passou?").

## Métricas

- Exponha só o necessário (no Spring: `health,info,metrics,prometheus`).
- Toda métrica com a etiqueta da aplicação.
- **"Média mente": use percentis** (p95, p99); ligue o histograma de latência.
- **Etiqueta pelo padrão da rota** (`/tarefas/{id}`), nunca por valor (`/tarefas/7`), id ou
  e-mail: alta cardinalidade derruba o Prometheus.
- Métricas de negócio com etiquetas de tipo e resultado
  (`eventos.publicados{tipo, resultado}`).

## Logs

- **Um identificador de requisição em toda linha** (MDC), reaproveitado do cabeçalho
  `X-Request-Id` do cliente e devolvido na resposta. Limpe o MDC no `finally`.
- Uma linha de acesso por requisição: método, rota-padrão, status, duração.
- Logs nas operações que criam, alteram e removem, no Service. Níveis INFO, WARN, ERROR.
- Nada de segredo ou dado pessoal em log.
- Log fora de laço.

## Painéis

- Painel organizado nos quatro sinais de ouro: tráfego, latência, erros, saturação.
- Painel é JSON versionado e provisionado por arquivo, não clicado à mão.

## Ferramentas de referência

Spring Boot Actuator + Micrometer, `prom/prometheus:v2.55.1`, `grafana/grafana:11.4.0`.

## Alertas e rastreamento

- Alertas (Alertmanager ou do próprio Grafana) para erro e latência acima do limite.
- Traces distribuídos (OpenTelemetry com Tempo ou Jaeger) quando houver mais de um serviço.
- Rastreamento de erros em produção (Sentry ou equivalente), inclusive no frontend.
- Monitoramento sintético de páginas e APIs públicas (uptime).
