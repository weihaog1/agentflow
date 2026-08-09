"""Measure exact-key response cache generation call reduction."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentflow.cache.keys import response_cache_key as production_response_cache_key
from agentflow.domain import WorkflowType

KEY_FIELDS = (
    "workspace_id",
    "corpus_revision",
    "workflow",
    "input",
    "document_ids",
    "prompt_version",
    "graph_version",
    "model",
    "top_k",
    "retriever_identity",
)
RETRIEVER_IDENTITY_FIELDS = (
    "retriever_version",
    "embedding_provider_id",
    "candidate_pool",
    "dense_weight",
    "sparse_weight",
)


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "benchmarks" / "cache-workload.json").is_file():
            return parent
    return Path.cwd()


REPOSITORY_ROOT = _repository_root()
DEFAULT_WORKLOAD = REPOSITORY_ROOT / "benchmarks" / "cache-workload.json"
DEFAULT_RESULT = REPOSITORY_ROOT / "benchmarks" / "results" / "cache-baseline.json"


def _resolved_query(query: Mapping[str, Any], defaults: Mapping[str, Any]) -> dict[str, Any]:
    return {**defaults, **query}


def response_cache_key(query: Mapping[str, Any]) -> str:
    missing = [field for field in KEY_FIELDS if field not in query]
    if missing:
        raise ValueError(f"benchmark query is missing cache key fields: {', '.join(missing)}")
    normalized_input = query["input"]
    document_ids = query["document_ids"]
    retriever_identity = query["retriever_identity"]
    if not isinstance(normalized_input, dict):
        raise ValueError("benchmark query input must be an object")
    if not isinstance(document_ids, list) or not all(
        isinstance(value, str) and value for value in document_ids
    ):
        raise ValueError("benchmark query document_ids must be a list of nonempty strings")
    if not isinstance(retriever_identity, Mapping):
        raise ValueError("benchmark query retriever_identity must be an object")
    missing_retriever_fields = [
        field for field in RETRIEVER_IDENTITY_FIELDS if field not in retriever_identity
    ]
    if missing_retriever_fields:
        raise ValueError(
            "benchmark query is missing retriever identity fields: "
            + ", ".join(missing_retriever_fields)
        )
    try:
        workflow = WorkflowType(str(query["workflow"]))
        corpus_revision = int(query["corpus_revision"])
        top_k = int(query["top_k"])
    except (TypeError, ValueError) as exc:
        raise ValueError("benchmark query has an invalid workflow or numeric identity") from exc
    return production_response_cache_key(
        workspace_id=str(query["workspace_id"]),
        corpus_revision=corpus_revision,
        workflow=workflow,
        normalized_input=normalized_input,
        document_ids=document_ids,
        prompt_version=str(query["prompt_version"]),
        graph_version=str(query["graph_version"]),
        model_id=str(query["model"]),
        top_k=top_k,
        retriever_identity=retriever_identity,
    )


def _load_workload(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    raw = path.read_bytes()
    data: dict[str, Any] = json.loads(raw)
    queries = data.get("queries")
    defaults = data.get("cache_identity_defaults")
    if data.get("schema_version") != 1 or not isinstance(queries, list) or not queries:
        raise ValueError("unsupported or empty cache workload")
    if not isinstance(defaults, Mapping):
        raise ValueError("cache workload must define cache_identity_defaults")
    request_ids = [query.get("request_id") for query in queries]
    if any(not value for value in request_ids) or len(request_ids) != len(set(request_ids)):
        raise ValueError("benchmark request_id values must be present and unique")
    resolved_queries = [_resolved_query(query, defaults) for query in queries]
    for query in resolved_queries:
        response_cache_key(query)
    return resolved_queries, raw


def run_benchmark(workload_path: Path = DEFAULT_WORKLOAD) -> dict[str, Any]:
    resolved_queries, raw = _load_workload(workload_path)
    cache: set[str] = set()
    cache_hits = 0
    for query in resolved_queries:
        key = response_cache_key(query)
        if key in cache:
            cache_hits += 1
        else:
            cache.add(key)
    total = len(resolved_queries)
    generation_calls = len(cache)
    avoided = total - generation_calls
    reduction_fraction = avoided / total
    return {
        "schema_version": 1,
        "benchmark": "response-cache-exact-repeat",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "command": "uv run python -m agentflow.benchmarks.cache --write",
        "environment": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.system(),
            "platform_release": platform.release(),
            "machine": platform.machine(),
        },
        "workload": {
            "path": str(workload_path.resolve().relative_to(REPOSITORY_ROOT)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "query_count": total,
            "unique_cache_keys": generation_calls,
            "exact_repeat_count": cache_hits,
            "cache_key_fields": list(KEY_FIELDS),
            "retriever_identity_fields": list(RETRIEVER_IDENTITY_FIELDS),
        },
        "metrics": {
            "generation_calls_without_cache": total,
            "generation_calls_with_cache": generation_calls,
            "generation_calls_avoided": avoided,
            "cache_hits": cache_hits,
            "cache_misses": generation_calls,
            "generation_call_reduction_fraction": reduction_fraction,
            "generation_call_reduction_percent": round(reduction_fraction * 100, 2),
        },
    }


def _stable_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": result["schema_version"],
        "benchmark": result["benchmark"],
        "workload": result["workload"],
        "metrics": result["metrics"],
    }


def verify_committed(
    workload_path: Path = DEFAULT_WORKLOAD,
    result_path: Path = DEFAULT_RESULT,
) -> dict[str, Any]:
    committed: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
    recomputed = run_benchmark(workload_path)
    if _stable_projection(committed) != _stable_projection(recomputed):
        raise ValueError("committed cache benchmark does not match the workload")
    metrics = committed["metrics"]
    expected_fraction = (
        metrics["generation_calls_avoided"] / metrics["generation_calls_without_cache"]
    )
    if metrics["generation_call_reduction_fraction"] != expected_fraction:
        raise ValueError("committed reduction fraction is not derived from raw counts")
    if metrics["generation_call_reduction_percent"] != round(expected_fraction * 100, 2):
        raise ValueError("committed reduction percentage is not derived from raw counts")
    return committed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true")
    action.add_argument("--verify-committed", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_committed:
            result = verify_committed(args.workload, args.result)
        else:
            result = run_benchmark(args.workload)
            if args.write:
                args.result.parent.mkdir(parents=True, exist_ok=True)
                args.result.write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"cache benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
