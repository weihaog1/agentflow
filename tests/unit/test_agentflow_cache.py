from __future__ import annotations

from agentflow.cache.keys import response_cache_key, retrieval_cache_key
from agentflow.cache.memory import InMemoryJsonCache
from agentflow.domain import WorkflowType


def test_response_cache_key_covers_every_correctness_dimension() -> None:
    base = {
        "workspace_id": "workspace-1",
        "corpus_revision": 4,
        "workflow": WorkflowType.QUESTION,
        "normalized_input": {"question": "What is the policy?"},
        "document_ids": ["doc-b", "doc-a"],
        "prompt_version": "prompt-v1",
        "graph_version": "graph-v1",
        "model_id": "local-v1",
        "top_k": 8,
        "retriever_identity": {
            "retriever_version": "hybrid-v1",
            "embedding_provider_id": "local-feature-hash-v1-384",
            "candidate_pool": 50,
            "dense_weight": 0.55,
            "sparse_weight": 0.45,
        },
    }
    original = response_cache_key(**base)

    for field, changed in (
        ("workspace_id", "workspace-2"),
        ("corpus_revision", 5),
        ("workflow", WorkflowType.BRIEF),
        ("normalized_input", {"question": "What changed?"}),
        ("prompt_version", "prompt-v2"),
        ("graph_version", "graph-v2"),
        ("model_id", "local-v2"),
        ("document_ids", ["doc-a", "doc-c"]),
        ("top_k", 9),
    ):
        candidate = {**base, field: changed}
        assert response_cache_key(**candidate) != original

    reordered = {**base, "document_ids": ["doc-a", "doc-b"]}
    assert response_cache_key(**reordered) == original

    for field, value in (
        ("retriever_version", "hybrid-v2"),
        ("embedding_provider_id", "openai:embedding-model:384"),
        ("candidate_pool", 75),
        ("dense_weight", 0.6),
        ("sparse_weight", 0.4),
    ):
        changed_identity = {**base["retriever_identity"], field: value}
        candidate = {**base, "retriever_identity": changed_identity}
        assert response_cache_key(**candidate) != original


def test_retrieval_cache_key_is_revision_scoped() -> None:
    first = retrieval_cache_key(
        workspace_id="workspace-1",
        corpus_revision=1,
        normalized_query="retention policy",
        retriever_identity={"retriever_version": "hybrid-v1"},
        document_ids=[],
        top_k=8,
    )
    second = retrieval_cache_key(
        workspace_id="workspace-1",
        corpus_revision=2,
        normalized_query="retention policy",
        retriever_identity={"retriever_version": "hybrid-v1"},
        document_ids=[],
        top_k=8,
    )

    assert first != second


async def test_memory_cache_expires_and_returns_defensive_copies(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("agentflow.cache.memory.time.monotonic", lambda: clock[0])
    cache = InMemoryJsonCache()
    source = {"result": {"answer": "grounded"}}

    await cache.set_json("key", source, ttl_seconds=10)
    source["result"]["answer"] = "mutated"
    cached = await cache.get_json("key")

    assert cached == {"result": {"answer": "grounded"}}
    assert cached is not None
    cached["result"]["answer"] = "changed again"
    assert await cache.get_json("key") == {"result": {"answer": "grounded"}}

    clock[0] = 111.0
    assert await cache.get_json("key") is None
