---
name: planejar
description: Planeja uma mudança de código antes de escrever qualquer linha. Entende o pedido, lê o código envolvido, compara opções, define os testes, quebra em passos pequenos e espera aprovação. Use para funcionalidade nova, refatoração, bug não trivial ou quando o usuário pedir "plano", "planejar" ou "como você faria".
---

# Planejar uma mudança

Objetivo: chegar a um plano aprovado pelo usuário antes de existir código. Mudar um plano é barato; mudar código não.

## Passos

1. **Entender o pedido.** Reescreva em uma frase o que deve mudar e qual é o critério de pronto.
   Se houver ambiguidade que muda o resultado, pergunte antes de seguir (no máximo 3 perguntas).
2. **Ler o contexto.** Leia o `AGENTS.md` (ou `CLAUDE.md`) do projeto, o `.kit-ia/projeto.yaml`
   (se existir), os padrões da área em `.kit-ia/padroes/` e os arquivos que a mudança toca.
   Anote as convenções que já existem (nomes, camadas, padrão de testes): o plano segue o que existe.
3. **Opções.** Se houver mais de um caminho razoável, liste 2 ou 3, com prós e contras em uma linha cada,
   e recomende um explicando o porquê. Se só houver um caminho óbvio, diga isso e siga.
4. **Testes primeiro.** Liste os casos: caminho feliz, erro de validação, limites (vazio, zero, máximo,
   duplicado) e o comportamento atual que não pode quebrar.
5. **Passos pequenos.** Quebre em passos que deixam o projeto compilando e com os testes passando
   ao fim de cada um. Para cada passo: arquivos, o que muda e como verificar.
6. **Riscos.** Migração de dados, mudança de contrato público, segurança, dependência nova
   (confirme que ela existe e qual versão; nunca invente nome de biblioteca ou de função).
7. **Parar.** Apresente o plano e espere o "ok" explícito. Não crie nem edite arquivos antes disso.
   Responder a uma pergunta de esclarecimento **não** é aprovação do plano.

## Formato da resposta

```
**Objetivo:** ...
**Critério de pronto:** ...
**Abordagem:** ... (alternativas descartadas: ... porque ...)
**Testes:**
- ...
**Passos:**
1. ... (arquivos: ...; como verificar: ...)
**Subagentes e scripts que serão disparados:** ... (o ok do plano autoriza só estes)
**Riscos:** ...
**Fora do escopo:** ...
```

## Não fazer
- Planejar sem ter lido o código que vai mudar.
- Passos grandes do tipo "implementar a funcionalidade".
- Incluir melhorias que ninguém pediu: registre em "Fora do escopo".
