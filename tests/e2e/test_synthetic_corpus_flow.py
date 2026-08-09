from __future__ import annotations

import os
import uuid

import pytest
from scripts.smoke_test import DEFAULT_CORPUS, run_smoke

BASE_URL = os.environ.get("AGENTFLOW_TEST_BASE_URL")
pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="set AGENTFLOW_TEST_BASE_URL to run the live end-to-end test",
)


def test_all_workflows_and_exact_response_cache() -> None:
    assert BASE_URL is not None
    result = run_smoke(
        base_url=BASE_URL,
        corpus_dir=DEFAULT_CORPUS,
        workspace_id=f"pytest-e2e-{uuid.uuid4().hex[:12]}",
        timeout_seconds=120.0,
    )

    assert result["documents_ingested"] == 5
    assert result["workflows_completed"] == 4
    assert result["verified_cache_hit"] is True
