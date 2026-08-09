# Response cache benchmark

This benchmark measures generation provider calls for a fixed synthetic workload. It does not claim a latency or cost reduction for arbitrary production traffic.

The workload contains 20 requests. Eleven have unique full response cache identities, and nine are later exact repeats. A key includes workspace, corpus revision, workflow, normalized input, document scope, top-k, prompt version, graph version, response model, and retrieval identity. Retrieval identity covers the retriever version, embedding provider identifier, candidate pool, dense weight, and sparse weight. The runner calls the production cache-key function, then calculates all reported counts and percentages from the workload.

Run and replace the raw artifact:

```sh
uv run python -m agentflow.benchmarks.cache --write
```

Verify that the committed artifact still matches the committed workload:

```sh
uv run python -m agentflow.benchmarks.cache --verify-committed
```

Changing a cache identity field should create a miss. Successful verified responses are the only entries admitted by this benchmark model.
