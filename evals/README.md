# Evaluation smoke suite

The smoke evaluator checks all three AgentFlow workflows against synthetic evidence. It verifies required answer facts, exact source quotations, minimum citation counts, and a basic untrusted-document guardrail.

The committed predictions are a deterministic harness fixture. They test the scorer itself and keep CI free of model keys. A provider or API adapter can export records in the same JSON Lines shape to score a real implementation.

Run the smoke gate:

```sh
uv run python evals/run_smoke.py
```

Each prediction record has `case_id`, `answer`, and `citations`. Each citation has `document` and `quote`. A quote is valid only when it appears in the named synthetic source.
