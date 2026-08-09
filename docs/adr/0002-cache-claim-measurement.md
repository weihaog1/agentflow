# ADR 0002: Measure generation calls with a verified response cache

- Status: Accepted
- Date: 2026-08-09

## Context

The original project description said caching reduced repeat LLM inference calls by 45 percent. A retrieval cache alone cannot support that claim because it skips retrieval work, not generation. The claim also needs a reproducible denominator and invalidation identity.

## Decision

Use separate retrieval and response caches. Admit a response only after citation verification succeeds. Key it by workspace, corpus revision, workflow, normalized input, document scope, top-k, prompt version, graph version, response model, and retrieval identity. Retrieval identity includes the retriever version, embedding provider identifier, candidate pool, dense weight, and sparse weight.

Publish a deterministic 20-request benchmark containing 11 unique full identities and 9 later exact repeats. The benchmark calls the production response cache-key function, records generation calls with and without the response cache, and calculates the reduction from raw counts. The committed verifier rejects an edited or stale result artifact.

The public claim is intentionally narrow:

> On the published 20-request exact-repeat workload, verified response caching skipped 9 of 20 generation calls, a 45 percent reduction.

It is not a general traffic, latency, token, or cost claim.

## Consequences

- Changing a corpus, document scope, retrieval configuration, top-k, graph, prompt, model, workflow, or normalized input produces a miss.
- Failed or unverified responses cannot enter the cache.
- The percentage remains auditable and can change when the workload changes.
- Retrieval-cache performance is measured separately and cannot be substituted for generation-call reduction.
