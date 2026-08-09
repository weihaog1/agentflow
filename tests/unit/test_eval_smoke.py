from __future__ import annotations

import json
from copy import deepcopy

from evals.run_smoke import (
    DEFAULT_CORPUS,
    DEFAULT_DATASET,
    DEFAULT_PREDICTIONS,
    _load_jsonl,
    evaluate,
)


def test_deterministic_predictions_pass_smoke_gate() -> None:
    dataset = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    predictions = _load_jsonl(DEFAULT_PREDICTIONS)

    result = evaluate(dataset, predictions, DEFAULT_CORPUS)

    assert result["passed"] is True
    assert result["metrics"]["passed_cases"] == result["metrics"]["case_count"]
    assert result["metrics"]["valid_citations"] == result["metrics"]["citation_count"]


def test_evaluator_rejects_unsupported_quote() -> None:
    dataset = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    predictions = deepcopy(_load_jsonl(DEFAULT_PREDICTIONS))
    predictions[0]["citations"][0]["quote"] = "A sentence absent from the source."

    result = evaluate(dataset, predictions, DEFAULT_CORPUS)

    assert result["passed"] is False
    assert result["metrics"]["citation_validity"] < 1.0
    assert result["cases"][0]["all_citations_valid"] is False


def test_evaluator_rejects_citation_path_escape() -> None:
    dataset = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    predictions = deepcopy(_load_jsonl(DEFAULT_PREDICTIONS))
    predictions[0]["citations"][0] = {
        "document": "../../AGENTS.md",
        "quote": "AgentFlow Engineering Contract",
    }

    result = evaluate(dataset, predictions, DEFAULT_CORPUS)

    assert result["passed"] is False
    assert result["cases"][0]["all_citations_valid"] is False
