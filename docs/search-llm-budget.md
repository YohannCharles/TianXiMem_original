# Search Internal LLM Budget

This report estimates internal LLM token usage and cost for the full official
question set and for 10,000-12,000 question runs. It covers only the components
inside Search:

1. query routing;
2. optional grounded planner;
3. Plan decomposition;
4. Plan step execution.

It excludes the final answer model, answer judging, embeddings, reranking, and
Qdrant.

## Price Basis

| Item | Price |
| --- | ---: |
| Input | USD 0.15 / 1M tokens |
| Output | USD 0.60 / 1M tokens |

Cost formula:

```text
cost = input_millions * 0.15 + output_millions * 0.60
```

## Evidence Used

The report combines three measured sources and one structural estimate.

### 1. Complete question universe

The complete official run contains:

- 8,783 scored Search questions;
- 10,144 total Search events, including 1,361 Search events without a gold
  answer.

Budgeting uses the 8,783 scored questions because those are the questions whose
saved answer contexts can be associated with routing results.

Evidence:

```text
eval/reports/runs/official-v1.2-answer-v2/summary.json
```

### 2. Complete saved-context token distribution

All 8,783 saved retrieved contexts were counted with the repository's
`o200k_base` tokenizer.

| Statistic | Final retrieved-context tokens |
| --- | ---: |
| Total | 147,886,643 |
| Mean per question | 16,837.8 |
| Median | 7,131 |
| P90 | 54,848 |
| P95 | 70,993 |
| P99 | 116,947 |
| Maximum | 117,722 |

These are final Search contexts, not the Plan per-round inputs. Plan sends the
current round's reranked top 20 documents.

### 3. Complete routing audit

The configured router model `Qwen/Qwen3.5-9B` classified all 8,783 selected
questions.

| Result | Questions | Share |
| --- | ---: | ---: |
| `DEFAULT` | 6,454 | 73.48% |
| `MULTI_HOP` | 2,329 | 26.52% |
| `degraded` | 175 | 1.99% |

All 175 degraded results were recorded as `DEFAULT`. For a conservative budget,
they are treated as possible missed `MULTI_HOP` questions:

```text
2,329 + 175 = 2,504 potential multi-hop questions
2,504 / 8,783 = 28.51%
```

The router audit itself used:

| Router usage | Tokens |
| --- | ---: |
| Input | 8,979,665 |
| Output | 24,557 |
| Questions with usage | 8,776 / 8,783 |

Evidence:

```text
eval/reports/runs/router-audit-qwen-20261026/routes.jsonl
eval/reports/runs/router-audit-qwen-20261026/progress.json
```

The run artifacts are intentionally untracked. The values above are the
reproducible measurements from that run.

### 4. Plan input structure

For the 2,504 conservative potential multi-hop questions, saved final contexts
were associated back to their routing results.

| Set | Questions | Mean final context | Median | P90 | Total tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Confirmed `MULTI_HOP` | 2,329 | 4,402.8 | 1,693 | 12,613 | 10,254,069 |
| Confirmed + degraded buffer | 2,504 | 4,293.7 | 964 | 12,518 | 10,751,548 |

A 6,026-question checkpoint run where both final context and round-local top 20
were available gives this ratio:

```text
mean round-local top 20 / mean final context = 0.4725
```

Applying that measured structural ratio to the routed question set:

```text
mean Plan documents per round = 4,293.7 * 0.4725 = 2,028.6 tokens
```

Measured fixed prompt sizes:

| Prompt component | Input tokens |
| --- | ---: |
| Plan decomposition | 999 |
| Plan step with no documents | 1,074 |
| Additional plan, history, and query allowance | 300 |

Output assumptions used for a loose budget:

| Output component | Tokens |
| --- | ---: |
| Decomposition JSON | 300 |
| Each Plan step answer JSON | 250 |

## Component Estimates

### Router

Measured for 8,783 questions:

```text
input  = 8.98M tokens
output = 0.025M tokens
```

### Grounded Planner

The historical full run did not save the exact grounded-planner call count.
The planner prompt has a maximum input of about 1,392 tokens and an output cap
of 256 tokens.

For 8,783 questions, the full-call upper bound is:

```text
input  = 8,783 * 1,392 = 12.23M tokens
output = 8,783 * 256   = 2.25M tokens
```

The budget report uses three sensitivity levels for the share of questions that
actually invoke the planner:

| Planner invocation rate | Input | Output |
| ---: | ---: | ---: |
| 25% | 3.06M | 0.56M |
| 50% | 6.11M | 1.12M |
| 100% | 12.23M | 2.25M |

### Plan decomposition

One decomposition call is reserved for every conservative potential
multi-hop question.

For 2,504 questions:

```text
input  = 2,504 * 999 = 2.50M tokens
output = 2,504 * 300 = 0.75M tokens
```

### Plan step execution

Per-round input:

```text
fixed step prompt                        1,074
additional plan/history/query allowance   300
estimated top-20 documents             2,029
                                         -----
per-round input                         3,403 tokens
```

Per-round output is estimated at 250 tokens.

| Plan rounds | Input for 2,504 questions | Output for 2,504 questions |
| ---: | ---: | ---: |
| 3 | 25.56M | 1.88M |
| 4 | 34.08M | 2.50M |

## Full 8,783-Question Totals

The tables below include Router, Plan decomposition, and Plan steps. The three
columns represent different assumptions for grounded-planner invocation.

### Three Plan rounds

| Planner rate | Total input | Total output | Cost |
| ---: | ---: | ---: | ---: |
| 25% | 40.10M | 3.22M | USD 7.95 |
| 50% | 43.15M | 3.78M | USD 8.74 |
| 100% | 49.27M | 4.90M | USD 10.33 |

### Four Plan rounds

| Planner rate | Total input | Total output | Cost |
| ---: | ---: | ---: | ---: |
| 25% | 48.62M | 3.84M | USD 9.60 |
| 50% | 51.67M | 4.40M | USD 10.39 |
| 100% | 57.79M | 5.53M | USD 11.99 |

## 10,000- and 12,000-Question Totals

The extrapolation preserves the measured routing share and the conservative
28.51% potential multi-hop share. It assumes a four-round Plan ceiling and a
full grounded-planner call for each listed planner rate.

| Questions | Planner rate | Input | Output | Cost |
| ---: | ---: | ---: | ---: | ---: |
| 10,000 | 25% | 55.4M | 4.37M | USD 9.93 |
| 10,000 | 50% | 58.8M | 5.01M | USD 11.83 |
| 10,000 | 100% | 65.8M | 6.29M | USD 13.64 |
| 12,000 | 25% | 66.4M | 5.25M | USD 13.11 |
| 12,000 | 50% | 70.6M | 6.02M | USD 14.20 |
| 12,000 | 100% | 79.0M | 7.55M | USD 16.38 |

## Recommended Budget

The model-based estimates above are lower than the recommended operational
budget because they do not reserve enough for tokenizer differences, prompt
evolution, retry behavior, timing-out calls that still consume input, and
future increases in Plan rounds or document size.

Recommended budget with an operational allowance:

| Questions | Input budget | Output budget | Estimated cost |
| ---: | ---: | ---: | ---: |
| 10,000 | 80M | 8M | USD 16.80 |
| 12,000 | 95M | 9.5M | USD 19.95 |

Recommended procurement amount:

```text
10,000 questions: about USD 17
12,000 questions: about USD 20
```

For a more conservative all-questions-routed, four-round capacity ceiling:

| Questions | Input | Output | Cost |
| ---: | ---: | ---: | ---: |
| 10,000 | 391.6M | 13.08M | USD 66.59 |
| 12,000 | 469.9M | 15.70M | USD 79.90 |

That ceiling is not a forecast. The measured routing result makes it roughly
seven to eight times larger than the expected workload.

## Main Risks

1. The routing audit used the configured Qwen router, not the eventual
   production `gpt-4o-mini` router. Route decisions can differ after changing
   models.
2. The complete historical run did not save grounded-planner call counts.
   The 100% planner column is the safe upper bound.
3. Plan decomposition output length and step-answer verbosity are structural
   estimates because the historical run did not save per-call LLM usage.
4. The Plan top-20 estimate uses a measured final-context/top-20 ratio from
   6,026 checkpoint-backed questions, not per-round top-20 text from all 8,783
   questions.
5. The 110k prompt ceiling may truncate about 2.84% of final contexts, but Plan
   round prompts are smaller than final contexts.
6. Provider tokenization can differ from local `o200k_base`; the operational
   allowance covers this.

## Conclusion

Using the completed 8,783-question routing audit and complete saved-context
measurements:

- expected Search-internal usage for 8,783 questions is about **40-58M input
  and 3.2-5.5M output tokens**;
- for 10,000 questions, the expected range is about **46-66M input and
  3.7-6.3M output tokens**;
- for 12,000 questions, the expected range is about **55-79M input and
  4.4-7.6M output tokens**.

For procurement, reserve:

```text
10,000 questions: 80M input + 8M output tokens = about USD 17
12,000 questions: 95M input + 9.5M output tokens = about USD 20
```

The answer and judge models are excluded from every number in this report.
