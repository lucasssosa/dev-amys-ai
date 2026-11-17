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

(ainda não implementado) `kit.py custo` lê os registros das sessões (Claude Code, Codex e outros) e o registro
de eventos das tasks, sem gastar token de modelo, e mostra tokens por task, papel e modelo
(entrada, saída e cache) e o tempo de cada etapa.

Enquanto a medição automática não estiver disponível, relate o que estiver disponível (uso informado pelo agente ao fim de cada
subagente, duração aproximada) e diga que a medição é parcial.

## Relatório do lote

```text
Lote: landing-v1, 4 tasks (BL-LU-12 a 15)        Duração: 1h40
| Task      | Estado    | Tokens  | Tempo | Redespachos |
| BL-LU-12  | integrada | 310 mil | 25 min | 0 |
| BL-LU-13  | devolvida | 520 mil | 41 min | 1 | <- estourou o orçamento por task
Maior gasto: leitura de capturas no coordenador (passar para o leitor).
```

Termine com uma melhoria concreta para o próximo lote, quando houver.
