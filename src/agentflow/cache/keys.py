"""Canonical revision-scoped cache key construction."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from agentflow.domain import WorkflowType


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def retrieval_cache_key(
    *,
    workspace_id: str,
    corpus_revision: int,
    normalized_query: str,
    retriever_identity: Mapping[str, Any],
    document_ids: list[str],
    top_k: int,
) -> str:
    digest = _digest(
        {
            "query": normalized_query,
            "retriever": retriever_identity,
            "document_ids": sorted(document_ids),
            "top_k": top_k,
        }
    )
    return f"agentflow:retrieval:{workspace_id}:{corpus_revision}:{digest}"


def response_cache_key(
    *,
    workspace_id: str,
    corpus_revision: int,
    workflow: WorkflowType,
    normalized_input: dict[str, Any],
    document_ids: list[str],
    prompt_version: str,
    graph_version: str,
    model_id: str,
    top_k: int,
    retriever_identity: Mapping[str, Any],
) -> str:
    digest = _digest(
        {
            "workflow": workflow.value,
            "input": normalized_input,
            "document_ids": sorted(document_ids),
            "prompt": prompt_version,
            "graph": graph_version,
            "model": model_id,
            "top_k": top_k,
            "retriever": retriever_identity,
        }
    )
    return f"agentflow:response:{workspace_id}:{corpus_revision}:{digest}"
