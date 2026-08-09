from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentflow.domain import DocumentVersion


def test_object_storage_identity_is_version_aware_in_initial_schema() -> None:
    migration = (Path(__file__).resolve().parents[2] / "migrations" / "0001_initial.sql").read_text(
        encoding="utf-8"
    )

    assert "object_key text NOT NULL UNIQUE" not in migration
    assert "ON document_versions (object_key, object_version_id)" in migration
    assert "WHERE object_version_id IS NOT NULL" in migration
    assert "ON document_versions (object_key)" in migration
    assert "WHERE object_version_id IS NULL" in migration


def test_object_version_id_rejects_empty_values() -> None:
    for invalid_version in ("", "   "):
        with pytest.raises(ValidationError):
            DocumentVersion(
                document_id="0a0d7d1e-6d23-4a59-a8fd-7eb559501ef2",
                workspace_id="workspace-1",
                content_sha256="a" * 64,
                object_key="incoming/workspace-1/policy.pdf",
                object_version_id=invalid_version,
                size_bytes=1,
                media_type="application/pdf",
            )
