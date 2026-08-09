"""Score AgentFlow predictions against the committed synthetic smoke dataset."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path(__file__).with_name("smoke-dataset.json")
DEFAULT_PREDICTIONS = Path(__file__).parent / "fixtures" / "deterministic-predictions.jsonl"
DEFAULT_CORPUS = REPO_ROOT / "examples" / "synthetic-corpus"


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_all(haystack: str, needles: Iterable[str]) -> bool:
    folded = _fold(haystack)
    return all(_fold(needle) in folded for needle in needles)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on {path}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"prediction on {path}:{line_number} must be an object")
        records.append(record)
    return records


@dataclass(frozen=True)
class CitationCheck:
    document: str
    quote: str
    valid: bool


def _validate_citation(citation: Mapping[str, Any], corpus_dir: Path) -> CitationCheck:
    document = citation.get("document")
    quote = citation.get("quote")
    if not isinstance(document, str) or not isinstance(quote, str) or not quote.strip():
        return CitationCheck(str(document or ""), str(quote or ""), False)

    source_path = (corpus_dir / document).resolve()
    try:
        source_path.relative_to(corpus_dir.resolve())
    except ValueError:
        return CitationCheck(document, quote, False)
    if not source_path.is_file():
        return CitationCheck(document, quote, False)
    source = source_path.read_text(encoding="utf-8")
    return CitationCheck(document, quote, _fold(quote) in _fold(source))


def evaluate(
    dataset: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
    corpus_dir: Path = DEFAULT_CORPUS,
) -> dict[str, Any]:
    """Return case details and aggregate evidence quality metrics."""

    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("evaluation dataset must contain cases")
    by_id: dict[str, Mapping[str, Any]] = {}
    for prediction in predictions:
        case_id = prediction.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("each prediction needs a case_id")
        if case_id in by_id:
            raise ValueError(f"duplicate prediction for {case_id}")
        by_id[case_id] = prediction

    expected_ids = {case["case_id"] for case in cases}
    extra_ids = set(by_id) - expected_ids
    if extra_ids:
        extras = ", ".join(sorted(extra_ids))
        raise ValueError(f"predictions contain unknown case ids: {extras}")

    case_results: list[dict[str, Any]] = []
    total_facts = 0
    passed_facts = 0
    total_citations = 0
    valid_citations = 0
    guardrail_passes = 0

    for case in cases:
        case_id = case["case_id"]
        prediction = by_id.get(case_id, {"answer": "", "citations": []})
        answer = prediction.get("answer", "")
        citations = prediction.get("citations", [])
        if not isinstance(answer, str) or not isinstance(citations, list):
            raise ValueError(f"prediction {case_id} has invalid answer or citations")

        checked = [_validate_citation(citation, corpus_dir) for citation in citations]
        total_citations += len(checked)
        valid_citations += sum(item.valid for item in checked)

        fact_results: list[dict[str, Any]] = []
        for fact in case.get("expected_facts", []):
            total_facts += 1
            answer_ok = _contains_all(answer, fact.get("answer_contains", []))
            evidence_ok = any(
                citation.valid
                and citation.document == fact.get("source")
                and _contains_all(citation.quote, fact.get("evidence_contains", []))
                for citation in checked
            )
            passed = answer_ok and evidence_ok
            passed_facts += int(passed)
            fact_results.append(
                {
                    "fact_id": fact["fact_id"],
                    "answer_present": answer_ok,
                    "supported_by_valid_citation": evidence_ok,
                    "passed": passed,
                }
            )

        forbidden = case.get("forbidden_answer_contains", [])
        guardrail_passed = not any(_fold(item) in _fold(answer) for item in forbidden)
        guardrail_passes += int(guardrail_passed)
        minimum_citations_met = len(checked) >= int(case.get("minimum_citations", 1))
        citations_valid = bool(checked) and all(item.valid for item in checked)
        case_passed = (
            all(item["passed"] for item in fact_results)
            and minimum_citations_met
            and citations_valid
            and guardrail_passed
        )
        case_results.append(
            {
                "case_id": case_id,
                "workflow": case["workflow"],
                "passed": case_passed,
                "minimum_citations_met": minimum_citations_met,
                "all_citations_valid": citations_valid,
                "guardrail_passed": guardrail_passed,
                "facts": fact_results,
            }
        )

    case_count = len(cases)
    passed_cases = sum(item["passed"] for item in case_results)
    metrics = {
        "case_pass_rate": passed_cases / case_count,
        "fact_coverage": passed_facts / total_facts if total_facts else 0.0,
        "citation_validity": valid_citations / total_citations if total_citations else 0.0,
        "guardrail_pass_rate": guardrail_passes / case_count,
        "case_count": case_count,
        "passed_cases": passed_cases,
        "fact_count": total_facts,
        "passed_facts": passed_facts,
        "citation_count": total_citations,
        "valid_citations": valid_citations,
    }
    thresholds = dataset.get("thresholds", {})
    threshold_results = {name: metrics[name] >= float(value) for name, value in thresholds.items()}
    return {
        "schema_version": 1,
        "dataset_id": dataset.get("dataset_id"),
        "passed": all(threshold_results.values()),
        "metrics": metrics,
        "thresholds": thresholds,
        "threshold_results": threshold_results,
        "cases": case_results,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        predictions = _load_jsonl(args.predictions)
        result = evaluate(dataset, predictions, args.corpus)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
