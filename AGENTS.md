# AgentFlow Engineering Contract

AgentFlow is an evidence-first document workflow engine. Keep every feature tied to one of three workflows: cited question answering, document comparison, or executive brief generation.

## Required boundaries

- PostgreSQL is the system of record for documents, chunks, jobs, runs, and citations.
- Object storage holds raw files only.
- Redis holds disposable caches and rate-limit state only.
- Lambda validates S3 events and forwards normalized jobs. It does not parse, chunk, embed, or call an LLM.
- The worker owns ingestion and other long-running work.
- LangGraph state stores artifacts and identifiers, never chain-of-thought or secrets.
- A cached response is valid only for the exact workspace, corpus revision, document scope, retrieval identity, top-k value, prompt version, graph version, response model, workflow, and normalized input.
- Never publish a benchmark percentage that was not produced by a committed command and result artifact.

## Quality gates

Run these before committing:

```sh
uv run ruff check .
uv run mypy src
uv run pytest
uv run python -m agentflow.benchmarks.cache --verify-committed
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

Integration checks that need containers:

```sh
docker compose config
docker compose up -d --build
uv run python scripts/smoke_test.py
docker compose down
```

## Style

- Prefer narrow modules with explicit protocols over global clients.
- Use typed domain objects at boundaries.
- Make retries idempotent and observable.
- Treat uploaded documents as untrusted input.
- Keep the demo usable without cloud credentials or a paid model.
- Use plain language in documentation. Do not use em dashes.
