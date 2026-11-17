---
name: revisar
description: Revisa um diff de código procurando bugs, falhas de segurança, testes fracos, mudanças fora do escopo e violações das convenções do projeto, com achados ordenados por gravidade. Use antes de um commit ou PR, ou quando o usuário pedir "revisar", "code review" ou "o que tem de errado neste diff".
---

# Revisar um diff

Objetivo: encontrar o que vai dar errado em produção antes que chegue lá. Cada achado precisa de um cenário concreto.

## Antes de começar
- Obtenha o diff: o que foi colado na conversa; senão `git diff` e `git diff --staged`;
  numa branch, `git diff main...HEAD`.
- Leia o `AGENTS.md` do projeto: as regras de "Arquitetura (não quebrar)" também são critério de revisão.
  Se existir `.kit-ia/padroes/`, leia os padrões das áreas tocadas pelo diff.
- Leia o código em volta das linhas alteradas, não só o diff.

## O que procurar (nesta ordem)

1. **Correção.** Lógica errada, condição invertida, erro de off-by-one, `null`/vazio não tratado,
   exceção engolida, concorrência, recurso não fechado, transação faltando.
2. **Segurança.** Segredo no código; injeção (SQL, comando, caminho de arquivo, prompt);
   entrada não validada na porta de entrada; falta de autorização; dado sensível em log.
3. **Coisas inventadas.** Função, opção ou biblioteca que não existe na versão usada.
   Em caso de dúvida, confira na documentação e marque como "a confirmar".
4. **Testes.** Regra nova sem teste; teste que só testa o mock; falta de caso de erro ou de limite;
   asserção fraca (só "não lançou exceção").
5. **Escopo.** Mudanças que não têm relação com o pedido (refatoração de carona, formatação em massa).
6. **Convenções e simplicidade.** Regras do `AGENTS.md`, duplicação, código morto, nomes enganosos.

## Formato da resposta

Para cada achado, do mais grave ao menos grave:

```
[ALTA|MÉDIA|BAIXA] arquivo:linha: problema em uma frase
  Cenário: entrada/estado concreto -> resultado errado
  Sugestão: correção em uma ou duas linhas
```

Depois: uma linha sobre o que está bom e o veredito (**aprovar**, **aprovar com ajustes** ou **refazer**).
Se não houver achados, diga isso claramente; não invente problemas para preencher a lista.

## Não fazer
- Reportar estilo pessoal como bug.
- Achado sem cenário concreto (se for só suspeita, marque "a confirmar").
- Alterar o código durante a revisão, a menos que o usuário peça.
