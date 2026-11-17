# Integração HTTP (nossa API como cliente)

- O cliente fica isolado num pacote próprio (`client/`), atrás de uma classe nossa.
- O contrato do outro lado vira records próprios; leia só os campos que usa.
- **Todo cliente HTTP tem timeout**, o menor que ainda funciona
  (ex.: conexão 2 s, leitura 5 s).
- **Timeout quer dizer "não sei":** a operação pode ter acontecido. Repetir pode fazer duas
  vezes.
- **As regras vêm antes da chamada:** valide primeiro, chame depois.
- Traduza a falha num ponto só: 502 para falha do outro lado, 504 para demora. Nunca 500,
  nunca 400.
- Resposta parcial com aviso (fallback) quando a parte externa é acessória.
- Cache para dado que muda pouco; em produção, Caffeine ou Redis em vez de mapa em memória.
- Uma chamada em lote em vez de N chamadas (N+1).
- Teste com servidor falso: URL montada, 500 do outro lado, JSON quebrado.

## Resiliência e métricas

- Disjuntor (circuit breaker, ex.: Resilience4j) quando o outro lado cai com frequência.
- Retentativa só em operação idempotente, com limite e espera crescente.
- Métrica de latência e de erro por serviço externo (Timer com etiqueta de resultado).
