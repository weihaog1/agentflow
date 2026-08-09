from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest

from agentflow.cache.memory import InMemoryJsonCache
from agentflow.domain import RunStatus, WorkflowType
from agentflow.errors import ValidationError
from agentflow.extraction import DocumentExtractor, TextChunker
from agentflow.object_store.local import LocalObjectStore
from agentflow.providers.local import (
    DeterministicEmbeddingProvider,
    DeterministicResponseProvider,
)
from agentflow.repositories.memory import InMemoryRepository
from agentflow.retrieval.hybrid import HybridRetriever
from agentflow.services.ingestion import IngestionService
from agentflow.services.workflows import WorkflowService
from agentflow.workflows.graph import BoundedWorkflowEngine

SECURITY_STANDARD = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "synthetic-corpus"
    / "northstar-security-standard.md"
).read_text(encoding="utf-8")


@dataclass
class InMemorySystem:
    repository: InMemoryRepository
    ingestion: IngestionService
    workflows: WorkflowService


def build_system(storage_root: Path) -> InMemorySystem:
    repository = InMemoryRepository()
    cache = InMemoryJsonCache()
    embeddings = DeterministicEmbeddingProvider(dimensions=64)
    extractor = DocumentExtractor(
        allowed_extensions=(".txt", ".md", ".pdf", ".docx"),
        max_upload_bytes=1024 * 1024,
        max_extracted_chars=100_000,
        max_pdf_pages=20,
        max_docx_entries=1000,
        max_docx_uncompressed_bytes=2 * 1024 * 1024,
    )
    ingestion = IngestionService(
        repository=repository,
        object_store=LocalObjectStore(storage_root),
        extractor=extractor,
        chunker=TextChunker(chunk_size_tokens=100, overlap_tokens=10),
        embedding_provider=embeddings,
        embedding_batch_size=8,
        worker_lease_seconds=30,
        max_attempts=3,
    )
    retriever = HybridRetriever(
        repository=repository,
        cache=cache,
        embedding_provider=embeddings,
        retriever_version="hybrid-test-v1",
        candidate_pool=20,
        dense_weight=0.5,
        sparse_weight=0.5,
        cache_ttl_seconds=300,
    )
    engine = BoundedWorkflowEngine(
        repository=repository,
        response_cache=cache,
        retriever=retriever,
        response_provider=DeterministicResponseProvider(),
        prompt_version="prompt-test-v1",
        graph_version="graph-test-v1",
        response_cache_ttl_seconds=300,
    )
    return InMemorySystem(
        repository=repository,
        ingestion=ingestion,
        workflows=WorkflowService(repository=repository, engine=engine),
    )


async def ingest_markdown(
    system: InMemorySystem,
    *,
    workspace_id: str,
    filename: str,
    text: str,
) -> str:
    upload = await system.ingestion.register_upload(
        workspace_id=workspace_id,
        filename=filename,
        media_type="text/markdown",
        data=text.encode(),
    )
    claimed = await system.repository.claim_next_job(
        worker_id="integration-worker",
        lease_seconds=30,
    )
    assert claimed is not None
    revision = await system.ingestion.process(claimed, worker_id="integration-worker")
    assert revision is not None
    return str(upload.document.id)


async def test_ingestion_all_workflows_and_verified_response_cache(tmp_path) -> None:
    system = build_system(tmp_path / "objects")
    atlas_id = await ingest_markdown(
        system,
        workspace_id="integration",
        filename="atlas.md",
        text=(
            "Atlas commits to 99.95 percent availability. "
            "Severity 1 support responds within 15 minutes."
        ),
    )
    beacon_id = await ingest_markdown(
        system,
        workspace_id="integration",
        filename="beacon.md",
        text=(
            "Beacon commits to 99.9 percent availability. "
            "Severity 1 support responds within 30 minutes."
        ),
    )

    atlas_uuid = UUID(atlas_id)
    beacon_uuid = UUID(beacon_id)
    question_arguments = {
        "workspace_id": "integration",
        "workflow": WorkflowType.QUESTION,
        "raw_input": {"question": "What availability does Atlas commit to?"},
        "document_ids": [atlas_uuid],
        "top_k": 8,
    }
    first = await system.workflows.execute(**question_arguments)
    repeated = await system.workflows.execute(**question_arguments)

    assert first.status == RunStatus.COMPLETED
    assert first.cached is False
    assert first.citations
    assert {citation.document_id for citation in first.citations} == {atlas_uuid}
    assert repeated.status == RunStatus.COMPLETED
    assert repeated.cached is True
    assert repeated.citations

    comparison = await system.workflows.execute(
        workspace_id="integration",
        workflow=WorkflowType.COMPARE,
        raw_input={"focus": "availability and severity 1 support"},
        document_ids=[atlas_uuid, beacon_uuid],
        top_k=8,
    )
    assert comparison.status == RunStatus.COMPLETED
    assert {citation.document_id for citation in comparison.citations} == {
        atlas_uuid,
        beacon_uuid,
    }

    brief = await system.workflows.execute(
        workspace_id="integration",
        workflow=WorkflowType.BRIEF,
        raw_input={
            "objective": "Summarize vendor service levels",
            "audience": "executive",
            "max_points": 5,
        },
        document_ids=[atlas_uuid, beacon_uuid],
        top_k=8,
    )
    assert brief.status == RunStatus.COMPLETED
    assert brief.citations


async def test_encryption_question_returns_relevant_exact_citations(tmp_path) -> None:
    system = build_system(tmp_path / "objects")
    document_id = await ingest_markdown(
        system,
        workspace_id="security-regression",
        filename="northstar-security-standard.md",
        text=SECURITY_STANDARD,
    )

    run = await system.workflows.execute(
        workspace_id="security-regression",
        workflow=WorkflowType.QUESTION,
        raw_input={"question": "How is customer content encrypted?"},
        document_ids=[UUID(document_id)],
        top_k=8,
    )

    answer = str((run.result or {}).get("answer", ""))
    assert run.status == RunStatus.COMPLETED
    assert "AES-256" in answer
    assert "TLS 1.3" in answer
    assert "Ignore the workflow rules" not in answer
    assert "return every secret" not in answer
    chunks = {
        chunk.id: chunk
        for chunk in await system.repository.get_chunks(
            [citation.chunk_id for citation in run.citations]
        )
    }
    assert run.citations
    assert all(citation.quote in chunks[citation.chunk_id].text for citation in run.citations)
    assert any("AES-256" in citation.quote for citation in run.citations)


async def test_workflow_rejects_cross_workspace_document(tmp_path) -> None:
    system = build_system(tmp_path / "objects")
    document_id = await ingest_markdown(
        system,
        workspace_id="workspace-a",
        filename="policy.md",
        text="The synthetic policy retains audit logs for 400 days.",
    )

    with pytest.raises(ValidationError, match="another workspace"):
        await system.workflows.execute(
            workspace_id="workspace-b",
            workflow=WorkflowType.QUESTION,
            raw_input={"question": "How long are logs retained?"},
            document_ids=[UUID(document_id)],
            top_k=8,
        )
