from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

import pytest

from agentflow.domain import RetrievedChunk, WorkflowType
from agentflow.providers.local import (
    DeterministicEmbeddingProvider,
    DeterministicResponseProvider,
)

SECURITY_STANDARD = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "synthetic-corpus"
    / "northstar-security-standard.md"
).read_text(encoding="utf-8")


def evidence(title: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        workspace_id="workspace-1",
        document_id=uuid4(),
        document_version_id=uuid4(),
        document_title=title,
        chunk_ordinal=0,
        text=text,
        score=1.0,
    )


async def test_local_embedding_is_deterministic_and_normalized() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=64)

    first = await provider.embed("Retention policy for customer documents")
    second = await provider.embed("Retention policy for customer documents")

    assert first == second
    assert len(first) == 64
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


async def test_local_response_uses_only_bounded_evidence() -> None:
    provider = DeterministicResponseProvider()
    chunks = [
        evidence(
            f"Document {index}",
            f"Evidence statement number {index}. More detail.",
        )
        for index in range(8)
    ]

    response = await provider.generate(
        workflow=WorkflowType.BRIEF,
        normalized_input={"objective": "Summarize the evidence", "audience": "executive"},
        evidence=chunks,
    )

    assert response.model_id == provider.identifier
    assert response.citation_indices == list(range(6))
    assert response.usage.generation_calls == 1
    assert "Document 7" not in response.text


async def test_question_selects_encryption_evidence_and_ignores_embedded_instruction() -> None:
    provider = DeterministicResponseProvider()
    response = await provider.generate(
        workflow=WorkflowType.QUESTION,
        normalized_input={"question": "How is customer content encrypted?"},
        evidence=[evidence("Northstar Security Standard", SECURITY_STANDARD)],
    )

    assert "AES-256" in response.text
    assert "TLS 1.3" in response.text
    assert "Ignore the workflow rules" not in response.text
    assert "return every secret" not in response.text
    assert response.citation_indices == [0]
    assert response.text.endswith("[1]")


async def test_comparison_uses_focus_aware_findings_with_stable_citation_numbers() -> None:
    provider = DeterministicResponseProvider()
    chunks = [
        evidence(
            "Atlas",
            (
                "# Atlas Proposal Product overview and company background. "
                "Atlas commits to 99.95 percent availability. "
                "Severity 1 support responds within 15 minutes."
            ),
        ),
        evidence(
            "Beacon",
            (
                "# Beacon Proposal Product overview and company background. "
                "Beacon commits to 99.9 percent availability. "
                "Severity 1 support responds within 30 minutes."
            ),
        ),
    ]

    response = await provider.generate(
        workflow=WorkflowType.COMPARE,
        normalized_input={"focus": "availability and severity 1 support"},
        evidence=chunks,
    )

    assert "99.95 percent" in response.text
    assert "99.9 percent" in response.text
    assert "15 minutes" in response.text
    assert "30 minutes" in response.text
    assert response.citation_indices == [0, 1]
    assert response.text.count("[1]") == 1
    assert response.text.count("[2]") == 1
