# agent

The agent package implements the `MULTI_HOP` search executor. It expands evidence coverage but never produces the final Search response.

## Files

```text
coq_prompt.py       react prompt
parse.py            react JSON extraction and validation
coq.py              react executor
plan_prompts.py     plan decomposition and step prompts
plan_parse.py       plan validation
plan.py             plan executor
```

## Modes

| Mode | Behavior |
| --- | --- |
| `react` | Each round retrieves, reranks a round-local set, asks the model whether evidence is sufficient and what to search next, then stops or repeats. |
| `plan` | Decomposes the query into one to four ordered steps. Each round answers the step whose evidence was just retrieved. Program code binds placeholders and controls the next step. |

The selected mode is constructed during service assembly. The Search pipeline only calls the executor interface and does not branch on the internal mode.

Each mode has its own prompts, parsers, stop reasons, and tests. Shared helpers are limited to pure rendering, timing, and JSON extraction utilities.

## Executor Contract

Inputs:

- original query and `user_id`;
- requested `top_k`;
- retrieval, rerank, store, and LLM collaborators.

Outputs:

- candidate evidence merged by stable ID;
- the final rerank query;
- diagnostic execution status, rounds, and stop reason.

The executor does not:

- write memory;
- return intermediate answers as evidence;
- perform final packaging;
- perform the final candidate rerank;
- access the HTTP layer or query router.

## Ordering Rules

- Retrieve the full requested candidate depth before round-local reranking.
- Rebuild the document-to-stable-ID mapping every round.
- Render each document once.
- Preserve evidence from previous rounds by stable ID.
- Send the current round's reranked top-N documents in full; do not apply an input-token budget or backfill dropped slots.
- React also sends all previously selected evidence, deduplicated by stable ID. Plan sends only question, answer, and source IDs from completed steps, not whole prior-round documents.

## Plan Recovery

The executor performs one recovery retrieval using the original query after
`dependency_unresolved`, `binding_conflict`, `invalid_output`,
`llm_unavailable`, or `plan_invalid`:

1. Retrieve and rerank up to the requested `top_k` candidates.
2. Merge them after the plan-step candidates by stable ID.
3. Stop when the pool reaches `top_k`; do not invent candidates to fill it.
4. Use the original query for final reranking.
5. Do not present the execution record as memory or as a final answer.
6. Do not add a plan step or an LLM call for recovery.

`retrieval_error`, `llm_error`, `unbound_placeholder`, `max_rounds`, and
`plan_complete` do not trigger this recovery path. A failed recovery retrieval
preserves existing candidates; the reason remains a named diagnostic.

## Failure Behavior

Optional-path failures return a result with a named reason. They do not raise into the HTTP layer and do not turn a valid Search into a 500.

`router.enabled` chooses whether to enter this path. `agentic.enabled` controls whether the executor exists. `agentic.force` is a diagnostic override and requires the executor to be enabled.

## Tests

- `tests/test_agent.py`: react state machine.
- `tests/test_plan.py`: plan state machine.
- `tests/test_plan_decompose_tool.py`: plan parsing and evaluation helpers.

Tests use fake LLM, retrieval, rerank, and store collaborators. No test calls a real model.
