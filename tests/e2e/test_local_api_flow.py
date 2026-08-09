from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agentflow.api.app import create_app
from agentflow.config import Settings


def wait_for_job(
    client: TestClient,
    job_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/jobs/{job_id}",
            params={"workspace_id": workspace_id},
        )
        assert response.status_code == 200
        job = response.json()
        if job["status"] == "completed":
            assert job["stage"] == "ready"
            return job
        assert job["status"] not in {"failed"}
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not complete")


def upload_markdown(client: TestClient, filename: str, text: str) -> tuple[str, str]:
    response = client.post(
        "/api/v1/documents",
        data={"workspace_id": "e2e-local", "title": Path(filename).stem},
        files={"file": (filename, text.encode(), "text/markdown")},
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    wait_for_job(client, payload["job"]["id"], "e2e-local")
    return str(payload["document"]["id"]), str(payload["job"]["id"])


def test_local_api_ingestion_three_workflows_and_response_cache(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        repository_backend="memory",
        cache_backend="memory",
        storage_backend="local",
        local_storage_path=tmp_path / "objects",
        embedded_worker=True,
        worker_poll_seconds=0.05,
        chunk_size_tokens=100,
        chunk_overlap_tokens=10,
        embedding_dimensions=64,
        json_logs=False,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/readyz").json()["status"] == "ready"

        atlas_id, atlas_job_id = upload_markdown(
            client,
            "atlas.md",
            "Atlas commits to 99.95 percent availability and a 15-minute response.",
        )
        beacon_id, _ = upload_markdown(
            client,
            "beacon.md",
            "Beacon commits to 99.9 percent availability and a 30-minute response.",
        )

        question_request = {
            "workspace_id": "e2e-local",
            "question": "What availability does Atlas commit to?",
            "document_ids": [atlas_id],
            "top_k": 8,
        }
        question = client.post("/api/v1/workflows/question", json=question_request)
        assert question.status_code == 200, question.text
        assert question.json()["status"] == "completed"
        assert question.json()["verified"] is True
        assert question.json()["cached"] is False
        assert question.json()["citations"]

        document_lookup = client.get(
            f"/api/v1/documents/{atlas_id}",
            params={"workspace_id": "e2e-local"},
        )
        job_lookup = client.get(
            f"/api/v1/jobs/{atlas_job_id}",
            params={"workspace_id": "e2e-local"},
        )
        assert document_lookup.status_code == 200
        assert job_lookup.status_code == 200

        documents = client.get(
            "/api/v1/documents",
            params={"workspace_id": "e2e-local"},
        )
        assert documents.status_code == 200
        assert documents.json()["corpus_revision"] == 2

        for path in (
            f"/api/v1/documents/{atlas_id}",
            f"/api/v1/jobs/{atlas_job_id}",
        ):
            denied = client.get(path, params={"workspace_id": "another-workspace"})
            assert denied.status_code == 404
            assert denied.json()["error"]["code"] == "not_found"

        repeated = client.post("/api/v1/workflows/question", json=question_request)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["cached"] is True
        assert repeated.json()["citations"]

        run_id = repeated.json()["run_id"]
        stored_run = client.get(
            f"/api/v1/runs/{run_id}",
            params={"workspace_id": "e2e-local"},
        )
        denied_run = client.get(
            f"/api/v1/runs/{run_id}",
            params={"workspace_id": "another-workspace"},
        )
        assert stored_run.status_code == 200
        assert denied_run.status_code == 404
        assert denied_run.json()["error"]["code"] == "not_found"

        comparison = client.post(
            "/api/v1/workflows/compare",
            json={
                "workspace_id": "e2e-local",
                "document_ids": [atlas_id, beacon_id],
                "focus": "availability and response time",
                "top_k": 8,
            },
        )
        assert comparison.status_code == 200, comparison.text
        assert comparison.json()["status"] == "completed"
        assert comparison.json()["verified"] is True
        assert {item["document_id"] for item in comparison.json()["citations"]} == {
            atlas_id,
            beacon_id,
        }

        brief = client.post(
            "/api/v1/workflows/brief",
            json={
                "workspace_id": "e2e-local",
                "document_ids": [atlas_id, beacon_id],
                "objective": "Summarize vendor service levels",
                "audience": "executive",
                "max_points": 5,
                "top_k": 8,
            },
        )
        assert brief.status_code == 200, brief.text
        assert brief.json()["status"] == "completed"
        assert brief.json()["verified"] is True
        assert brief.json()["citations"]

        evidence_gap = client.post(
            "/api/v1/workflows/question",
            json={
                "workspace_id": "empty-workspace",
                "question": "What evidence exists?",
                "document_ids": [],
                "top_k": 8,
            },
        )
        assert evidence_gap.status_code == 200, evidence_gap.text
        assert evidence_gap.json()["status"] == "evidence_gap"
        assert evidence_gap.json()["verified"] is False
        assert evidence_gap.json()["citations"] == []

        listed = client.get("/api/v1/runs", params={"workspace_id": "e2e-local"})
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 4
