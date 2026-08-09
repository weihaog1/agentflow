from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("AGENTFLOW_TEST_BASE_URL")
pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="set AGENTFLOW_TEST_BASE_URL to run live integration tests",
)


def test_live_health_readiness_and_metrics() -> None:
    assert BASE_URL is not None
    with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        metrics = client.get("/metrics")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["content-type"]
