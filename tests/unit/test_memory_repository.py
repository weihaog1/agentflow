from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

import pytest

from agentflow.domain import (
    Chunk,
    Document,
    DocumentStatus,
    DocumentVersion,
    IngestionJob,
    IngestionStage,
    JobStatus,
    utc_now,
)
from agentflow.errors import ConflictError
from agentflow.providers.local import DeterministicEmbeddingProvider
from agentflow.repositories.memory import InMemoryRepository
from agentflow.repositories.postgres import PostgresRepository


def upload_models() -> tuple[Document, DocumentVersion, IngestionJob]:
    document = Document(
        workspace_id="workspace-1",
        title="Synthetic retention policy",
        filename="retention.md",
        media_type="text/markdown",
    )
    version = DocumentVersion(
        document_id=document.id,
        workspace_id=document.workspace_id,
        content_sha256="a" * 64,
        object_key=f"{document.workspace_id}/{document.id}/version.md",
        size_bytes=128,
        media_type=document.media_type,
    )
    job = IngestionJob(
        workspace_id=document.workspace_id,
        document_id=document.id,
        document_version_id=version.id,
        idempotency_key="upload-retention-v1",
        max_attempts=3,
    )
    return document, version, job


async def test_upload_is_idempotent_and_repository_returns_copies() -> None:
    repository = InMemoryRepository()
    document, version, job = upload_models()

    created = await repository.create_upload(
        document=document,
        version=version,
        job=job,
    )
    duplicate_document, duplicate_version, duplicate_job = upload_models()
    duplicate_job.idempotency_key = job.idempotency_key
    duplicate = await repository.create_upload(
        document=duplicate_document,
        version=duplicate_version,
        job=duplicate_job,
    )

    assert created.created is True
    assert duplicate.created is False
    assert duplicate.document.id == created.document.id
    created.document.title = "mutated outside repository"
    stored = await repository.get_document(document.id)
    assert stored.title == "Synthetic retention policy"


async def test_job_lease_completion_increments_revision_and_enables_search() -> None:
    repository = InMemoryRepository()
    document, version, job = upload_models()
    await repository.create_upload(document=document, version=version, job=job)

    claimed = await repository.claim_next_job(worker_id="worker-1", lease_seconds=30)
    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING

    embedding_provider = DeterministicEmbeddingProvider(dimensions=32)
    text = "Approved deletion requests complete within fourteen calendar days."
    chunk = Chunk(
        workspace_id=document.workspace_id,
        document_id=document.id,
        document_version_id=version.id,
        ordinal=0,
        text=text,
        token_count=len(text.split()),
        embedding=await embedding_provider.embed(text),
        locator={"paragraph": 1},
    )
    revision = await repository.complete_ingestion(
        job_id=job.id,
        worker_id="worker-1",
        chunks=[chunk],
    )

    assert revision == 1
    assert await repository.get_corpus_revision(document.workspace_id) == 1
    query_embedding = await embedding_provider.embed("deletion calendar days")
    results = await repository.hybrid_search(
        workspace_id=document.workspace_id,
        query="deletion calendar days",
        query_embedding=query_embedding,
        document_ids=[document.id],
        top_k=5,
        candidate_pool=10,
        dense_weight=0.5,
        sparse_weight=0.5,
    )
    assert [result.chunk_id for result in results] == [chunk.id]
    assert results[0].document_title == document.title


async def test_completion_requires_current_worker_lease() -> None:
    repository = InMemoryRepository()
    document, version, job = upload_models()
    await repository.create_upload(document=document, version=version, job=job)
    await repository.claim_next_job(worker_id="worker-1", lease_seconds=30)

    wrong_document_id = uuid4()
    chunk = Chunk(
        workspace_id=document.workspace_id,
        document_id=wrong_document_id,
        document_version_id=version.id,
        ordinal=0,
        text="synthetic evidence",
        token_count=2,
        embedding=[1.0, 0.0],
    )
    with pytest.raises(ConflictError, match="not owned"):
        await repository.complete_ingestion(
            job_id=job.id,
            worker_id="worker-2",
            chunks=[chunk],
        )


async def test_expired_final_attempt_is_terminalized_before_other_job_is_claimed() -> None:
    repository = InMemoryRepository()
    document, version, expired = upload_models()
    document.status = DocumentStatus.PROCESSING
    version.status = DocumentStatus.PROCESSING
    expired.status = JobStatus.RUNNING
    expired.stage = IngestionStage.EMBEDDING
    expired.attempt = expired.max_attempts
    expired.lease_owner = "lost-worker"
    expired.lease_until = utc_now() - timedelta(seconds=1)
    await repository.create_upload(document=document, version=version, job=expired)

    next_document, next_version, next_job = upload_models()
    next_job.idempotency_key = "upload-retention-v2"
    await repository.create_upload(
        document=next_document,
        version=next_version,
        job=next_job,
    )

    claimed = await repository.claim_next_job(worker_id="worker-2", lease_seconds=30)

    assert claimed is not None
    assert claimed.id == next_job.id
    terminal = await repository.get_job(expired.id)
    assert terminal.status == JobStatus.FAILED
    assert terminal.stage == IngestionStage.FAILED
    assert terminal.error_code == "lease_expired"
    assert terminal.lease_owner is None
    assert terminal.completed_at is not None
    assert (await repository.get_document(document.id)).status == DocumentStatus.FAILED
    assert (await repository.get_document_version(version.id)).status == DocumentStatus.FAILED


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Connection:
    def __init__(self, claimed: IngestionJob) -> None:
        self.claimed = claimed
        self.executed: list[str] = []

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, query: str, *_args: object) -> str:
        self.executed.append(query)
        return "UPDATE 1"

    async def fetchrow(self, query: str, *_args: object) -> dict[str, Any]:
        assert self.executed, "terminalization must execute before the next claim"
        return {
            **self.claimed.model_dump(),
            "status": JobStatus.RUNNING.value,
            "stage": IngestionStage.DOWNLOADING.value,
        }


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


async def test_postgres_terminalizes_final_leases_before_claiming_other_work() -> None:
    document, version, job = upload_models()
    del document, version
    connection = _Connection(job)
    repository = PostgresRepository(dsn="postgresql://unused")
    repository._pool = cast(Any, _Pool(connection))

    claimed = await repository.claim_next_job(worker_id="worker-2", lease_seconds=30)

    assert claimed is not None
    assert claimed.id == job.id
    terminalization_sql = connection.executed[0]
    assert "attempt >= max_attempts" in terminalization_sql
    assert "error_code = 'lease_expired'" in terminalization_sql
    assert "UPDATE documents" in terminalization_sql
    assert "UPDATE document_versions" in terminalization_sql
