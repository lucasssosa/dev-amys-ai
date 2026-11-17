# Mensageria

Os exemplos usam RabbitMQ com Spring AMQP.

## Desenho

- Exchange do tipo tópico, durável (`tarefas.eventos`); fila durável (`tarefas.notificacoes`);
  routing key `<entidade>.<evento>` (`tarefa.criada`, `tarefa.concluida`).
- Evento é um record pequeno: `{tipo, id, dados mínimos, ocorridoEm}`, em JSON.
- **O Service não conhece o cliente do broker:** publica por um `Publisher` próprio, em `messaging/`.
- Topologia declarada em arquivo versionado (`definitions.json`), não criada à mão no painel.

## Comportamento

- **Publique depois de gravar.**
- **Broker fora do ar não derruba a requisição:** capture a falha, registre em WARN e conte
  na métrica com `resultado=falha`.
- O consumidor roda em outra thread, sem bloquear o HTTP.
- **Meça publicado contra consumido**: se o consumido não acompanha, a fila está acumulando.
- Teste a exchange, a routing key e o broker caído.

## Confiabilidade e contratos

Em fila nova, inclua estes pontos no plano:
- **Fila de mensagens mortas (DLQ)** para o que falhou depois das retentativas.
- **Retentativa com limite e espera crescente**; sem limite, uma mensagem ruim trava a fila.
- **Consumidor idempotente:** a mesma mensagem entregue duas vezes não pode gerar efeito
  duplicado (guarde o id processado).
- **Entrega garantida (outbox):** gravar e publicar na mesma transação, quando perder evento
  não é aceitável.
- Kafka quando houver necessidade de reprocessar o histórico ou volume muito alto;
  RabbitMQ para filas de trabalho.
- Contrato do evento versionado; campo novo é opcional.
