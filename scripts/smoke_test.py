"""Exercise the live AgentFlow API with the committed synthetic corpus."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO_ROOT / "examples" / "synthetic-corpus"
TERMINAL_FAILURES = {"cancelled", "failed"}


class SmokeFailure(RuntimeError):
    """Raised when a live smoke assertion fails."""


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:1000]
        raise SmokeFailure(
            f"{response.request.method} {response.request.url} returned "
            f"{response.status_code}: {body}"
        ) from exc
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{response.request.url} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{response.request.url} returned a non-object JSON body")
    return payload


def _wait_ready(client: httpx.Client, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            health = client.get("/healthz")
            ready = client.get("/readyz")
            if health.status_code == 200 and ready.status_code == 200:
                return
            last_error = f"health={health.status_code}, ready={ready.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise SmokeFailure(f"API did not become ready within {timeout_seconds}s: {last_error}")


def _upload(
    client: httpx.Client,
    *,
    workspace_id: str,
    path: Path,
) -> dict[str, Any]:
    with path.open("rb") as source:
        response = client.post(
            "/api/v1/documents",
            data={"workspace_id": workspace_id, "title": path.stem.replace("-", " ").title()},
            files={"file": (path.name, source, "text/markdown")},
        )
    payload = _json_response(response)
    for field in ("document", "version", "job"):
        if not isinstance(payload.get(field), Mapping):
            raise SmokeFailure(f"upload response is missing {field}")
    return payload


def _wait_for_job(
    client: httpx.Client,
    job_id: str,
    workspace_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        payload = _json_response(
            client.get(
                f"/api/v1/jobs/{job_id}",
                params={"workspace_id": workspace_id},
            )
        )
        status = str(payload.get("status", "unknown"))
        stage = str(payload.get("stage", "unknown"))
        last_status = f"status={status}, stage={stage}"
        if status == "completed" and stage == "ready":
            return payload
        if status in TERMINAL_FAILURES:
            detail = payload.get("error") or payload.get("last_error") or "no error detail"
            raise SmokeFailure(f"job {job_id} failed: {detail}")
        time.sleep(0.5)
    raise SmokeFailure(f"job {job_id} timed out after {last_status}")


def _run_workflow(
    client: httpx.Client,
    path: str,
    body: Mapping[str, Any],
    *,
    expected_documents: set[str],
) -> dict[str, Any]:
    payload = _json_response(client.post(path, json=body))
    if payload.get("status") != "completed":
        raise SmokeFailure(f"workflow {path} did not complete: {payload.get('status')}")
    if payload.get("verified") is not True:
        raise SmokeFailure(f"workflow {path} did not return verified evidence")
    if not payload.get("run_id"):
        raise SmokeFailure(f"workflow {path} did not return a run_id")
    citations = payload.get("citations")
    if not isinstance(citations, list) or not citations:
        raise SmokeFailure(f"workflow {path} returned no citations")
    for citation in citations:
        if not isinstance(citation, Mapping):
            raise SmokeFailure(f"workflow {path} returned an invalid citation")
        if citation.get("document_id") not in expected_documents:
            raise SmokeFailure(f"workflow {path} cited a document outside the request")
        if not str(citation.get("quote", "")).strip():
            raise SmokeFailure(f"workflow {path} returned an empty citation quote")
    run = _json_response(
        client.get(
            f"/api/v1/runs/{payload['run_id']}",
            params={"workspace_id": body["workspace_id"]},
        )
    )
    if run.get("run_id") != payload["run_id"]:
        raise SmokeFailure("stored run does not match workflow response")
    return payload


def run_smoke(
    *,
    base_url: str,
    corpus_dir: Path,
    workspace_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run ingestion plus all three evidence workflows against a live service."""

    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise SmokeFailure("synthetic corpus manifest contains no documents")

    by_name: dict[str, str] = {}
    job_ids: list[str] = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=15.0) as client:
        _wait_ready(client, timeout_seconds)
        for entry in documents:
            path = corpus_dir / entry["path"]
            upload = _upload(client, workspace_id=workspace_id, path=path)
            document_id = str(upload["document"]["id"])
            job_id = str(upload["job"]["id"])
            by_name[entry["path"]] = document_id
            job_ids.append(job_id)
            _wait_for_job(client, job_id, workspace_id, timeout_seconds)

        security_id = by_name["northstar-security-standard.md"]
        question_body = {
            "workspace_id": workspace_id,
            "question": "How is customer content encrypted?",
            "document_ids": [security_id],
            "top_k": 8,
        }
        question = _run_workflow(
            client,
            "/api/v1/workflows/question",
            question_body,
            expected_documents={security_id},
        )
        repeated_question = _run_workflow(
            client,
            "/api/v1/workflows/question",
            question_body,
            expected_documents={security_id},
        )
        if question.get("cached") is not False or repeated_question.get("cached") is not True:
            raise SmokeFailure("exact repeated question did not produce a verified cache hit")

        atlas_id = by_name["atlas-service-proposal.md"]
        beacon_id = by_name["beacon-service-proposal.md"]
        comparison = _run_workflow(
            client,
            "/api/v1/workflows/compare",
            {
                "workspace_id": workspace_id,
                "document_ids": [atlas_id, beacon_id],
                "focus": "availability and severity 1 support",
                "top_k": 8,
            },
            expected_documents={atlas_id, beacon_id},
        )

        review_id = by_name["q3-operating-review.md"]
        brief = _run_workflow(
            client,
            "/api/v1/workflows/brief",
            {
                "workspace_id": workspace_id,
                "document_ids": [review_id],
                "objective": "Summarize Q3 progress, decisions, risks, and milestones.",
                "audience": "executive",
                "max_points": 5,
                "top_k": 8,
            },
            expected_documents={review_id},
        )

        runs = _json_response(
            client.get("/api/v1/runs", params={"workspace_id": workspace_id, "limit": 50})
        )
        items = runs.get("items")
        if not isinstance(items, list) or len(items) < 4:
            raise SmokeFailure("run list did not include completed smoke workflows")

        metrics = client.get("/metrics")
        metrics.raise_for_status()
        if "text/plain" not in metrics.headers.get("content-type", ""):
            raise SmokeFailure("metrics endpoint did not return Prometheus text")

    return {
        "schema_version": 1,
        "workspace_id": workspace_id,
        "corpus_revision": manifest.get("revision"),
        "documents_ingested": len(by_name),
        "jobs_completed": len(job_ids),
        "workflows_completed": 4,
        "verified_cache_hit": True,
        "run_ids": {
            "question": question["run_id"],
            "question_cached": repeated_question["run_id"],
            "comparison": comparison["run_id"],
            "brief": brief["run_id"],
        },
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="AgentFlow API origin without an /api suffix.",
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Workspace to use. The default is an isolated smoke workspace.",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    workspace_id = args.workspace_id or f"smoke-{uuid.uuid4().hex[:12]}"
    try:
        result = run_smoke(
            base_url=args.base_url,
            corpus_dir=args.corpus,
            workspace_id=workspace_id,
            timeout_seconds=args.timeout,
        )
    except (OSError, ValueError, KeyError, httpx.HTTPError, SmokeFailure) as exc:
        print(f"smoke test failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
