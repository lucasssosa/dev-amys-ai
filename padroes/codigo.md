# Código (todas as áreas)

## Comentários

- **Comentários didáticos e objetivos: explicam o porquê, não repetem o que o código diz.**
  ```java
  // Ruim: incrementa o contador
  // Bom: o broker fora do ar não pode derrubar o cadastro; contamos a falha para o painel.
  ```
- Comente decisões, regras de negócio (com o identificador, ex.: `R1`) e o motivo de um
  contorno. Não comente o óbvio.
- Não remova comentário existente sem motivo.
- Se o `AGENTS.md` do projeto proíbe comentários novos, ele vence.

## Idioma e nomes

- Siga o idioma do projeto. Projeto novo do usuário: código, nomes e comentários em português.
- Nome diz o que é, sem abreviação obscura. Classes seguem o padrão da camada
  (`LivroController`, `LivroService`, `LivroRequestDTO`).

## Edição

- **Edição pontual, nunca reescrita de arquivo.** Reescrever um arquivo inteiro esconde
  mudanças no diff e apaga trabalho de outras tasks.
- Siga as convenções que o código já tem; não introduza padrão novo por conta própria.
- Métodos pequenos, com uma responsabilidade.
- Código morto sai; código comentado "para depois" também.
