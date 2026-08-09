# ADR 0001: Evidence-first bounded workflows

- Status: Accepted
- Date: 2026-08-09

## Context

The original portfolio concept named LangChain, LangGraph, FastAPI, PostgreSQL, Redis, AWS, and Docker. A naive implementation could turn those names into disconnected resume theater. The system needs one coherent reason for each dependency and must run without paid services.

## Decision

Build an evidence-first document workflow engine with three bounded workflows: cited question answering, document comparison, and executive brief generation.

Use LangGraph only for visible workflow state and routing. Use LangChain tools as constrained adapters around retrieval and document operations. Keep ingestion in a durable worker. Use PostgreSQL plus pgvector as the system of record and hybrid index, Redis for disposable caches, S3 or MinIO for raw files, and a thin S3 event Lambda that forwards normalized jobs.

Ship deterministic local embedding and response providers for the zero-key demo. Real model providers implement the same protocols.

## Consequences

- The project demonstrates orchestration, evidence handling, cache correctness, and failure recovery instead of open-ended autonomy.
- Local setup remains useful without an OpenAI key or AWS account.
- The response-cache benchmark can measure skipped generation calls honestly.
- The initial release does not include authentication, billing, web search, multi-agent planning, or Kubernetes.

