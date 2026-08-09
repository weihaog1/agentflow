"""Repository protocol for durable AgentFlow business records."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from agentflow.domain import (
    Chunk,
    Document,
    DocumentVersion,
    IngestionJob,
    IngestionStage,
    RetrievedChunk,
    UploadRecord,
    WorkflowRun,
    WorkflowType,
)


class Repository(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def ping(self) -> bool: ...

    async def create_upload(
        self,
        *,
        document: Document,
        version: DocumentVersion,
        job: IngestionJob,
    ) -> UploadRecord: ...

    async def find_upload_by_idempotency(self, idempotency_key: str) -> UploadRecord | None: ...

    async def get_document(self, document_id: UUID) -> Document: ...

    async def list_documents(self, workspace_id: str) -> list[Document]: ...

    async def get_document_version(self, version_id: UUID) -> DocumentVersion: ...

    async def get_job(self, job_id: UUID) -> IngestionJob: ...

    async def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> IngestionJob | None: ...

    async def update_job_stage(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        stage: IngestionStage,
        lease_seconds: int,
    ) -> IngestionJob: ...

    async def complete_ingestion(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        chunks: list[Chunk],
    ) -> int: ...

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        error_message: str,
        retry_at: datetime,
    ) -> IngestionJob: ...

    async def get_corpus_revision(self, workspace_id: str) -> int: ...

    async def hybrid_search(
        self,
        *,
        workspace_id: str,
        query: str,
        query_embedding: list[float],
        document_ids: list[UUID],
        top_k: int,
        candidate_pool: int,
        dense_weight: float,
        sparse_weight: float,
    ) -> list[RetrievedChunk]: ...

    async def get_chunks(self, chunk_ids: list[UUID]) -> list[Chunk]: ...

    async def create_run(self, run: WorkflowRun) -> WorkflowRun: ...

    async def save_run(self, run: WorkflowRun) -> WorkflowRun: ...

    async def get_run(self, run_id: UUID) -> WorkflowRun: ...

    async def list_runs(
        self,
        *,
        workspace_id: str,
        workflow: WorkflowType | None,
        limit: int,
    ) -> list[WorkflowRun]: ...
