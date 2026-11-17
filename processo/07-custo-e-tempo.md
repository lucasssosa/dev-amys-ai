# Custo e tempo

A autonomia vale enquanto o custo for visível. Toda task e todo lote têm orçamento, e todo lote
termina com um relatório de onde foram os tokens e o tempo.

## Orçamento

No `projeto.yaml`:

```yaml
orcamento:
  por_task: { tokens: 400000, minutos: 30 }
  por_lote: { tokens: 2000000, minutos: 120 }
  ao_estourar: parar_e_perguntar
```

Estourou: pare, diga quanto foi gasto, onde, e o que falta; pergunte se continua.
Aumentar o orçamento é decisão do usuário.

## Onde os tokens vão

| Gasta muito | Como evitar |
|---|---|
| Ler arquivos inteiros, logs e saídas longas no coordenador | Leitor ou script com resumo curto |
| Imagens (capturas de tela) no coordenador | Leitor de capturas devolve texto |
| Prompt de despacho que repete o contexto | Task autossuficiente e prompt enxuto |
| Retornos longos de subagentes | Limite de 2 KB por retorno |
| Redespachos por task mal escrita | Campos obrigatórios completos antes de despachar |
| Sessões longas (o contexto cresce a cada turno) | Lotes de 3 a 6 tasks; registrar estado e encerrar |
| Modelo maior que o necessário | `modelos` no `projeto.yaml`; modelo maior só com ok |
| Explorar o projeto para descobrir comandos | `comandos` preenchidos no `projeto.yaml` |

## Medição

`kit.py custo` lê métricas locais de Claude Code (incluindo subagentes), Codex,
Antigravity e chamadas de `kit.py executar`, sem gastar token de modelo nem guardar conversas.

```bash
python kit.py custo --desde 2026-11-16 --por task
python kit.py custo --por modelo --json
python kit.py custo --verificar-orcamento <pasta-do-projeto>
python kit.py cost --check-budget <pasta-do-projeto>
```

Use `--por task`, `modelo`, `agente` ou `papel`. A task vem da branch ou da pasta
(`BL-<sigla>-<número>`); chamadas diretas aceitam `executar --task ID`. Sem ID, fica
`(sem task)`. O filtro de data inclui a sessão inteira se houve atividade no período.
Entrada inclui cache; as colunas de cache são detalhamento, não tokens adicionais.
O Claude é deduplicado por requestId (ou message.id), contando uma vez o uso mais recente
de cada resposta. Em horários iguais ou ausentes, prevalece a última ocorrência lida.
No Codex, diferenças entre totais
acumulados pertencem ao modelo ativo no evento, sem somar cache ou raciocínio novamente.
Acumulados regressivos geram aviso e uso parcial, com custo desconhecido. O maior valor
comprovado de cada contador é preservado como limite inferior: só o que ultrapassa esse
máximo acrescenta consumo verificável. Assim, uma regressão não apaga um excesso de
orçamento já medido.

Minutos são da primeira à última atividade da sessão (incluindo pausas); somas podem conter
sessões simultâneas. Nas chamadas do kit, mede-se a duração da requisição.
Em sessões Claude com vários modelos, os intervalos vão para o último
modelo ativo, com o trecho anterior à primeira resposta atribuído ao primeiro modelo.
No Codex, consumo e intervalos são separados por modelo, pasta, branch e papel, inclusive
quando uma sessão é retomada em outra task. Cada intervalo vai para o grupo do próximo
evento de uso; o trecho final fica com o último grupo ativo, sem duplicar a duração da sessão.
Antigravity tem tokens desconhecidos e tempo parcial entre último envio e última alteração: os bancos
de conversas têm blobs sem formato de uso verificado. Leitura imutável, quando necessária,
avisa sobre dados possivelmente ainda no WAL. OpenCode/Kilo não têm leitor verificado.

Preencha `config/precos.json` na instalação do kit com tarifas por modelo em USD por milhão:
`entrada`, `saida`, `cache_leitura`, `cache_escrita`. Custo informado pelo provedor tem
prioridade. Sem preço ou uso conhecido, mostre `—` (`null` no JSON), nunca invente valores.
`*` na coluna Tokens indica medição parcial; dados desconhecidos não comprovam orçamento.

### Estimativa e limite superior

As regras de distribuição acima produzem a **estimativa**, usada para entender o gasto e
calcular custos por modelo. O relatório também mostra o **limite superior** de tokens e
minutos por task; somente ele é comparado ao orçamento. No JSON os campos são `tokens`,
`minutos`, `limite_superior_tokens`, `limite_superior_minutos` e `medicao_incompleta`.

- Claude: maior valor conhecido de cada contador entre todas as linhas da mesma resposta
  (`requestId` ou `message.id`), sem somar snapshots ou escolher apenas o primeiro/último.
  Entrada sem cache e os dois caches são normalizados para a entrada total.
- Codex: maiores acumulados conhecidos da sessão, sem diferenças entre contadores.
  Cache integra a entrada e raciocínio integra a saída; não são somados novamente.
  Um `total_tokens` informado também é preservado se for maior. Cada task tocada recebe
  o limite da sessão inteira, mesmo quando os deltas estimados são menores. A mesma sessão
  conta uma vez em cada grupo, inclusive se houve vários modelos ou papéis.
- Tempo conservador: primeira à última atividade da sessão para cada task tocada.
  Datas incluem a sessão inteira se qualquer atividade estiver na janela, mesmo atravessando
  a meia-noite. Repositório principal e todas as worktrees registradas pelo Git entram juntos.
- Registro ilegível, contadores inválidos ou obrigatórios ausentes tornam a medição incompleta.
  Sem contexto para identificar a task/projeto, a verificação também é bloqueada.
  `*` no limite indica que ele cobre apenas os dados recuperáveis, sem garantir um teto
  para a parte desconhecida; nesse caso a verificação nunca aprova o orçamento.

**Na dúvida, o erro é para o lado de "estourou".** Um limite conservador pode contar mais
que a estimativa, especialmente numa sessão retomada em várias tasks. Não some os limites
de tasks ou modelos para deduzir gasto exato quando compartilham uma sessão.

O registro do kit fica em `~/.kit-ia/uso.jsonl`. Os diretórios podem ser trocados por
`KIT_IA_HOME`, `KIT_IA_CLAUDE_DIR`, `KIT_IA_CODEX_DIR` e `KIT_IA_ANTIGRAVITY_DIR`.
Falha ao gravar uso ou telemetria inválida avisa sem impedir a execução da skill.

`--verificar-orcamento` lê `.kit-ia/projeto.yaml` da pasta indicada (ou um arquivo YAML),
filtra registros de dentro do projeto e das worktrees do mesmo repositório registradas pelo
Git, e compara tokens e minutos de cada task com
`orcamento.por_task`. Sai com 1 listando os excessos ou as tasks com "medição incompleta";
só sai com 0 se os dados forem completos e os limites não forem excedidos. Não interrompe
agentes nem consulta o registro de estados das tasks (ainda não implementado).
O leitor suporta mapas por indentação, mapas inline, listas simples, strings, números e
comentários; sintaxe não suportada gera erro com a linha.

## Relatório do lote

```bash
python kit.py custo --lote BL-LU-12,BL-LU-13
```

Formato de saída (valores apenas ilustrativos):

```text
Lote: BL-LU-12, BL-LU-13
| Task | Tokens estimados | Tempo (min) | Custo (USD) | Limite superior tokens | Limite superior min |
| --- | ---: | ---: | ---: | ---: | ---: |
| BL-LU-13 | 520000 | 41.00 | — | 520000 | 41.00 |
| BL-LU-12 | 310000 | 25.00 | — | 310000 | 25.00 |
Maior fonte de gasto: claude (tokens; preços incompletos).
```

O maior gasto usa USD quando todos os custos são conhecidos; caso contrário, usa tokens
medidos. Acrescente manualmente estado e redespachos, quando disponíveis.

Termine com uma melhoria concreta para o próximo lote, quando houver.
