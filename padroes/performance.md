# Performance e carga

## Método

1. **Meça antes de mudar.** Sem número de base, não há como provar melhora.
2. Rode a carga num ambiente local ou designado, nunca em produção sem ok.
3. Observe o painel enquanto a carga roda: requisições por segundo, p95 e erros por rota;
   publicado contra consumido; heap da JVM e pool de conexões.
4. Formule a hipótese do gargalo **com número** ("a query X leva 800 ms em 60% das chamadas").
5. Corrija uma coisa por vez.
6. **Meça de novo com o mesmo script e os mesmos parâmetros** e compare.

## Ferramentas de referência

- **k6** (`grafana/k6:0.54.0`) para HTTP, configurado por variável de ambiente
  (`CARGA_VUS`, `CARGA_SEGUNDOS`, `CARGA_TAXA`).
- **PerfTest** do RabbitMQ para filas.
- Perfil de queries com `pg_stat_statements` (zerar, carga, comparar).

## Regras

- Carga só em rotas de leitura, salvo autorização; o script tem uma guarda que bloqueia rotas
  com efeito real.
- A carga roda por script; o coordenador lê só o resumo.
- Filtrar e ordenar no banco; evitar N+1; paginação em listagens grandes.

## Cenários e critérios de carga

- **Limites de aprovação no próprio script** (ex.: p95 < 300 ms, erros < 1%), para a carga
  virar gate e não só gerador de gráfico.
- Tipos de teste: carga (uso esperado), estresse (até quebrar), pico (subida brusca) e
  resistência (horas, procura vazamento).
- Frontend: Core Web Vitals (LCP, INP, CLS) medidos com Lighthouse. (ver [frontend-e-design.md](frontend-e-design.md))
