# Gates e definição de pronto

Um gate é uma checagem que **bloqueia** a passagem para a etapa seguinte. Gate é rodado por
script ou comando, e a evidência é a saída dele, não a opinião do modelo.

## Os três níveis

| Nível | Quem roda | Onde | Quando | Bloqueia |
|---|---|---|---|---|
| **1. Task** | Executor | Na worktree da task | Antes do commit | O commit |
| **2. Integração** | Integrador | Na release | A cada task que entra | A entrada da task na release |
| **3. Promoção** | Script e usuário | Na release | Antes de subir para homologação ou principal | A promoção |

O que cada nível roda vem de `gates` no `projeto.yaml`: uma lista **padrão** mais o que cada
**tipo** de task acrescenta. Exemplo: uma task `frontend` acrescenta `auditoria_pagina` e
`validacao_visual` ao gate 3; uma task `seguranca` acrescenta `varredura_seguranca` ao gate 2.
O comando de cada item fica em `comandos`. Item sem comando configurado: diga isso ao usuário;
não invente o comando nem considere o gate verde.

Por que o executor roda o gate 1: com uma worktree por task, os testes dele não colidem com o
trabalho de outra sessão. Com `worktrees.modo: nenhum`, o gate 1 roda só os testes afetados,
nunca o build completo, e o resto fica para o gate 2.

## Regras
- **Não diga "funciona" sem ter visto funcionar.**
- **A medição vence o enunciado.** Nunca afrouxe asserção, mude valor esperado, desative ou
  pule teste para ficar verde.
- **Teste vermelho que a task não previa:** pare e relate antes de tocar.
- **Regra nova ganha teste unitário; rota, fila, ferramenta ou tela nova ganha teste de ponta a
  ponta.**
- **Validação visual é do usuário.** Diga o que ele precisa olhar e onde, com capturas.
- **Pelo menos um teste ou chamada passa pelo código real**, não só por mocks.

## Evidência mínima

| Área | Evidência |
|---|---|
| Backend | Suíte verde com os testes novos na contagem; a rota alterada chamada de verdade (status e corpo); um caso de erro |
| Frontend | Build verde; testes; capturas nos tamanhos de tela do projeto; auditoria da página |
| Infra | `docker compose ps` com tudo `healthy`; health check respondendo; subir do zero pelo README |
| Mensageria | Publicado e consumido medidos; broker fora do ar testado |
| Performance | Mesma carga antes e depois, mesmos parâmetros, números comparados |

(ainda não implementado) Cada gate grava a evidência em JSON junto da task (comando, código de saída, resumo,
duração). Até lá, relate em tabela:

| Verificação | Como | Resultado |
|---|---|---|
| Testes | `npm test` | 48 passando, 0 falhando |
| Página | capturas 375 / 768 / 1440 px | enviadas ao usuário |

Diga também o que **não** pôde ser verificado e por quê.

## Definição de pronto

Uma task está pronta quando:
1. os critérios de aceite foram medidos, não supostos;
2. o gate do nível atual está verde, com evidência;
3. o commit contém só os arquivos da task;
4. a seção "Resultado" da task está preenchida.
