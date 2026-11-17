# Testes

## Pirâmide

| Nível | O que sobe | Prova |
|---|---|---|
| Unitário | Só a classe; dependências viram mock | Regras, tradução, limites; aponta onde quebrou |
| Cliente externo | Servidor HTTP falso | URL montada, erro do outro lado vira exceção nossa |
| Ponta a ponta (E2E) | Aplicação inteira com banco e broker reais em container | HTTP, JSON, banco, migrations e mensageria juntos |
| Tela | Navegador real (Playwright) | O que o usuário vê e clica |

- **Muitos unitários, poucos E2E.**
- **Mocke o que não é seu ou é lento e instável; o que é seu e barato, use de verdade.**
  Serviço externo é mock; banco e broker são reais no E2E (Testcontainers); mapper é real
  até no unitário. Sem banco em memória no lugar do real.

## Como escrever

- Preparar, agir, conferir. Asserções legíveis (`assertThat`).
- **Um teste por regra, com o nome da regra** (`@DisplayName("R1: recusa o 4º empréstimo em aberto")`).
- Cubra: caminho feliz, limites (o 15º dia aceito, o 16º recusado), dado ruim e falha do
  outro lado (400, 404, 502, 504).
- **Assíncrono: espere por condição, nunca durma por tempo fixo** (`await().atMost(...)`).
- Teste de tela: simule a API externa (`page.route`), espere a resposta antes de agir.
- Observabilidade também se testa: health, métricas e cabeçalho de correlação.

## Organização

- Unitário no mesmo pacote da classe: `<Classe>Test`.
- E2E em `e2e/<Assunto>E2ETest`, herdando a base que sobe os containers uma vez.
- Playwright em `playwright/tests/*.spec.ts`.

## Regras

- **Regra nova ganha teste unitário; rota, fila, ferramenta ou tela nova ganha E2E.**
- **Nunca ajuste o teste só para ele passar, e nunca o desative.**
- Mudança de valor esperado é o achado mais grave de uma revisão.
- Teste que toca efeito real (pedido, pagamento, e-mail) usa serviço simulado e uma guarda
  que bloqueia a chamada real.
- Cobertura (JaCoCo, c8) é termômetro, não meta.
- Testes rodam no CI a cada push e bloqueiam o merge se falharem.
