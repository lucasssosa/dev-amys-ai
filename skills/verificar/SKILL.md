---
name: verificar
description: Verifica de verdade uma mudança em qualquer projeto. Descobre os comandos do projeto, compila, roda os testes, sobe a aplicação quando necessário e exercita o comportamento alterado, inclusive um caso de erro. Use antes de dizer que uma tarefa está pronta, ou quando o usuário pedir para "verificar", "testar tudo" ou "conferir se funciona".
---

# Verificar uma mudança

Objetivo: provar que a mudança funciona, e não só que compila. Sem evidência, não está pronto.

## Passos

1. **Descobrir os comandos.** Procure, nesta ordem:
   - `comandos` e `gates` do `.kit-ia/projeto.yaml`, se existir (dizem o que cada nível de gate roda);
   - as seções "Como rodar" e "Antes de dizer pronto" do `AGENTS.md` (ou `CLAUDE.md`);
   - os arquivos de build: `package.json` (scripts), `pom.xml`/`mvnw`, `build.gradle`, `pyproject.toml`,
     `go.mod`, `Cargo.toml`, `Makefile`, `docker-compose.yml`;
   - o README e a configuração de CI (`.github/workflows/`).
   Se não achar o comando de testes, pergunte em vez de adivinhar.
2. **Compilar / checar tipos.** Rode o build ou o type-check. Erro aqui: pare e corrija.
3. **Testes automatizados.** Rode a suíte completa e confira que os testes novos aparecem na contagem.
   Se algum falhar: pare, mostre o nome do teste e a mensagem, e investigue a causa.
   Nunca ajuste o teste só para ele passar, e nunca o desative.
4. **Lint e formatação**, se o projeto tiver.
5. **Rodar de verdade.** Se a mudança afeta comportamento em execução (rota, tela, comando, job),
   suba o que for preciso (banco, containers, aplicação) e exercite a mudança:
   `curl` numa rota, o comando na linha de comando, a tela no navegador.
   Mostre a entrada, a saída e o status.
6. **Caso de erro.** Exercite também uma entrada inválida e confira que a resposta de erro é a esperada.
7. **Relatório.** Responda com a tabela abaixo. Se algum passo não pôde ser feito, diga qual e por quê.

## Formato da resposta

| Verificação | Como | Resultado |
|---|---|---|
| Build | `<comando>` | ok / falhou (mensagem) |
| Testes | `<comando>` | 66 passando, 0 falhando |
| Comportamento | `curl ...` | 201, corpo `{...}` |
| Caso de erro | `curl ...` | 400, mensagem `...` |

## Não fazer
- Dizer "funciona" ou "deve funcionar" sem ter visto funcionar.
- Testar só o mock: pelo menos um teste ou chamada precisa passar pelo código real.
- Deixar processos rodando sem avisar (diga o que ficou de pé e como parar).
