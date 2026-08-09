from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from agentflow.benchmarks.cache import (
    DEFAULT_RESULT,
    DEFAULT_WORKLOAD,
    response_cache_key,
    run_benchmark,
    verify_committed,
)
from agentflow.cache.keys import response_cache_key as production_response_cache_key
from agentflow.domain import WorkflowType


def test_committed_result_is_derived_from_workload() -> None:
    result = verify_committed(DEFAULT_WORKLOAD, DEFAULT_RESULT)
    metrics = result["metrics"]
    total = metrics["generation_calls_without_cache"]
    avoided = metrics["generation_calls_avoided"]

    assert metrics["generation_call_reduction_fraction"] == avoided / total
    assert metrics["generation_call_reduction_percent"] == round(avoided / total * 100, 2)
    assert result["workload"]["exact_repeat_count"] == avoided
    assert result["workload"]["query_count"] == 20
    assert result["workload"]["unique_cache_keys"] == 11
    assert {"document_ids", "top_k", "retriever_identity"}.issubset(
        result["workload"]["cache_key_fields"]
    )
    assert set(result["workload"]["retriever_identity_fields"]) == {
        "retriever_version",
        "embedding_provider_id",
        "candidate_pool",
        "dense_weight",
        "sparse_weight",
    }


def test_workload_repeats_reduce_generation_calls() -> None:
    result = run_benchmark(Path(DEFAULT_WORKLOAD))

    assert (
        result["metrics"]["generation_calls_with_cache"]
        < result["metrics"]["generation_calls_without_cache"]
    )
    assert result["metrics"]["cache_hits"] == result["workload"]["exact_repeat_count"]


def test_benchmark_uses_the_production_response_cache_identity() -> None:
    retriever_identity = {
        "retriever_version": "hybrid-v1",
        "embedding_provider_id": "local-feature-hash-v1-384",
        "candidate_pool": 50,
        "dense_weight": 0.55,
        "sparse_weight": 0.45,
    }
    query = {
        "workspace_id": "workspace-1",
        "corpus_revision": 1,
        "workflow": "question",
        "input": {"question": "What is the policy?"},
        "document_ids": ["doc-b", "doc-a"],
        "prompt_version": "prompt-v1",
        "graph_version": "graph-v1",
        "model": "local-v1",
        "top_k": 8,
        "retriever_identity": retriever_identity,
    }
    reordered_documents = deepcopy(query)
    reordered_documents["document_ids"] = ["doc-a", "doc-b"]
    changed_graph = deepcopy(query)
    changed_graph["graph_version"] = "graph-v2"
    changed_top_k = deepcopy(query)
    changed_top_k["top_k"] = 12
    changed_retriever = deepcopy(query)
    changed_retriever["retriever_identity"]["candidate_pool"] = 75

    expected = production_response_cache_key(
        workspace_id="workspace-1",
        corpus_revision=1,
        workflow=WorkflowType.QUESTION,
        normalized_input={"question": "What is the policy?"},
        document_ids=["doc-b", "doc-a"],
        prompt_version="prompt-v1",
        graph_version="graph-v1",
        model_id="local-v1",
        top_k=8,
        retriever_identity=retriever_identity,
    )

    assert response_cache_key(query) == expected
    assert response_cache_key(query) == response_cache_key(reordered_documents)
    assert response_cache_key(query) != response_cache_key(changed_graph)
    assert response_cache_key(query) != response_cache_key(changed_top_k)
    assert response_cache_key(query) != response_cache_key(changed_retriever)
