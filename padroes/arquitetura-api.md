# Arquitetura de API

Os exemplos usam arquitetura em camadas em Java com Spring Boot.
Em outra stack, as regras valem com os nomes equivalentes.

## Camadas

```text
Controller (DTO) → Service (entidade) → Repository → banco
                    └── usa o Mapper
```

| Camada | Faz | Não faz |
|---|---|---|
| Controller | Liga verbo e rota, dispara a validação (`@Valid`), escolhe o status, documenta (OpenAPI) | Regra de negócio, acesso ao Repository, montar erro |
| Service | Regra de negócio; recebe e devolve DTO; busca entidades relacionadas pelo id | Conhecer HTTP; devolver `null` |
| Mapper | `toEntity`, `toResponse`, `updateEntity`, `applyPatch` | Consultar banco, ter regra |
| Repository | Interface de acesso a dados | Ser chamado por outra camada que não o Service |

- **A entidade não sobe além do Service. O Controller só enxerga DTO.**
- **Regra de negócio mora no Service.**
- **O Service lança exceção, nunca devolve `null`.**
- **Um DTO por uso** (request, response, patch, resumo, erro), em `record`, sem anotação de
  banco e sem entidade como campo. Relacionamento "entra como id, sai como objeto".
- **Conversão só no Mapper; o Mapper não consulta o banco.**
- Injeção por construtor.
- Coisa nova é pacote novo encostado no Service: `client/`, `messaging/`, `mcp/`,
  `observability/`.
- Regra de negócio implementada tem identificador (R1, R2...) na mensagem de erro.
  "Regra só descrita, sem código, não conta."

## Erros

- Um único tratador global (`@RestControllerAdvice`) devolve um DTO de erro:
  `{status, erro, mensagem, caminho, timestamp, campos[]}`.
- 404: recurso não encontrado. 400: regra de negócio, validação, JSON ilegível.
  502: serviço externo falhou. 504: serviço externo demorou. Nunca 500 para erro previsível.
- **Erro sem stack trace e sem mensagem interna no corpo.** O detalhe técnico vai para o log.
- Sem tratador "pega-tudo" de `Exception` que esconde bug.

## REST

- Rota no plural, minúscula, sem verbo (`/livros`, `/livros/{id}`).
- Listar 200; buscar 200 ou 404; criar 201 ou 400; atualizar 200, 400 ou 404; remover 204 ou 404.
- **Lista vazia é 200, não 404.**
- PUT substitui; PATCH é parcial (`null` = não mexer).
- Listagens grandes: paginação, ordenação e filtros.
- O contrato (OpenAPI) é gerado do código e documenta todos os status (`@ApiResponse`), com
  `example` em todo campo. Entidades não aparecem no contrato.
- Mudança compatível de contrato: campo novo opcional. Remover ou renomear campo quebra quem usa.

## Banco

- **O banco só muda por migration versionada** (`V<n>__<o_que_faz>.sql`).
- **Nunca edite uma migration que já rodou.**
- `ddl-auto=validate`: o mapeamento é conferido contra o banco, nunca gera tabela.
- Tabela no plural, snake_case; `NOT NULL` e `DEFAULT` também no banco.
- Filtrar e ordenar no banco, não em memória no Service.
- Duas gravações que precisam andar juntas: transação.
- Confira no Service antes de bater na chave estrangeira (devolve 4xx em vez de 500).

## Microsserviços

- Comece com uma API única (monolito modular).
- Separe um serviço só com motivo medido: escala, equipe ou ciclo de deploy diferentes.
- Cada serviço é dono do seu banco; comunicação por API ou eventos, nunca por tabela
  compartilhada.
