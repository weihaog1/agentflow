"""In-memory repository for deterministic local mode and unit tests."""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel

from agentflow.domain import (
    Chunk,
    Document,
    DocumentStatus,
    DocumentVersion,
    IngestionJob,
    IngestionStage,
    JobStatus,
    RetrievedChunk,
    UploadRecord,
    WorkflowRun,
    WorkflowType,
    utc_now,
)
from agentflow.errors import ConflictError, NotFoundError

_TERM_PATTERN = re.compile(r"[\w']+", re.UNICODE)


def _copy[ModelT: BaseModel](value: ModelT) -> ModelT:
    return value.model_copy(deep=True)


class InMemoryRepository:
    """A full behavioral repository, not a persistence substitute for production."""

    def __init__(self) -> None:
        self._documents: dict[UUID, Document] = {}
        self._versions: dict[UUID, DocumentVersion] = {}
        self._jobs: dict[UUID, IngestionJob] = {}
        self._chunks: dict[UUID, Chunk] = {}
        self._runs: dict[UUID, WorkflowRun] = {}
        self._idempotency: dict[str, UUID] = {}
        self._revisions: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def create_upload(
        self,
        *,
        document: Document,
        version: DocumentVersion,
        job: IngestionJob,
    ) -> UploadRecord:
        async with self._lock:
            existing_job_id = self._idempotency.get(job.idempotency_key)
            if existing_job_id is not None:
                existing_job = self._jobs[existing_job_id]
                existing_version = self._versions[existing_job.document_version_id]
                existing_document = self._documents[existing_job.document_id]
                return UploadRecord(
                    document=_copy(existing_document),
                    version=_copy(existing_version),
                    job=_copy(existing_job),
                    created=False,
                )
            identifiers_exist = (
                document.id in self._documents
                or version.id in self._versions
                or job.id in self._jobs
            )
            if identifiers_exist:
                raise ConflictError("upload identifiers already exist")
            document.latest_version_id = version.id
            self._documents[document.id] = _copy(document)
            self._versions[version.id] = _copy(version)
            self._jobs[job.id] = _copy(job)
            self._idempotency[job.idempotency_key] = job.id
            self._revisions.setdefault(document.workspace_id, 0)
            return UploadRecord(
                document=_copy(document),
                version=_copy(version),
                job=_copy(job),
            )

    async def find_upload_by_idempotency(self, idempotency_key: str) -> UploadRecord | None:
        async with self._lock:
            job_id = self._idempotency.get(idempotency_key)
            if job_id is None:
                return None
            job = self._jobs[job_id]
            return UploadRecord(
                document=_copy(self._documents[job.document_id]),
                version=_copy(self._versions[job.document_version_id]),
                job=_copy(job),
                created=False,
            )

    async def get_document(self, document_id: UUID) -> Document:
        async with self._lock:
            document = self._documents.get(document_id)
            if document is None:
                raise NotFoundError("document not found", details={"document_id": str(document_id)})
            return _copy(document)

    async def list_documents(self, workspace_id: str) -> list[Document]:
        async with self._lock:
            documents = [
                _copy(document)
                for document in self._documents.values()
                if document.workspace_id == workspace_id
            ]
        return sorted(documents, key=lambda item: item.created_at, reverse=True)

    async def get_document_version(self, version_id: UUID) -> DocumentVersion:
        async with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise NotFoundError(
                    "document version not found",
                    details={"version_id": str(version_id)},
                )
            return _copy(version)

    async def get_job(self, job_id: UUID) -> IngestionJob:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError("ingestion job not found", details={"job_id": str(job_id)})
            return _copy(job)

    async def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> IngestionJob | None:
        now = utc_now()
        async with self._lock:
            for expired in self._jobs.values():
                final_lease_expired = (
                    expired.status == JobStatus.RUNNING
                    and expired.lease_until is not None
                    and expired.lease_until <= now
                    and expired.attempt >= expired.max_attempts
                )
                if not final_lease_expired:
                    continue
                expired.status = JobStatus.FAILED
                expired.stage = IngestionStage.FAILED
                expired.lease_owner = None
                expired.lease_until = None
                expired.error_code = "lease_expired"
                expired.error_message = "worker lease expired after final attempt"
                expired.updated_at = now
                expired.completed_at = now
                document = self._documents[expired.document_id]
                version = self._versions[expired.document_version_id]
                if document.latest_version_id == version.id:
                    document.status = DocumentStatus.FAILED
                    document.updated_at = now
                version.status = DocumentStatus.FAILED
            eligible = [
                job
                for job in self._jobs.values()
                if (
                    job.status in {JobStatus.PENDING, JobStatus.RETRYING}
                    and job.next_attempt_at <= now
                    and job.attempt < job.max_attempts
                )
                or (
                    job.status == JobStatus.RUNNING
                    and job.lease_until is not None
                    and job.lease_until <= now
                    and job.attempt < job.max_attempts
                )
            ]
            if not eligible:
                return None
            job = min(eligible, key=lambda item: (item.next_attempt_at, item.created_at))
            job.status = JobStatus.RUNNING
            job.stage = IngestionStage.DOWNLOADING
            job.attempt += 1
            job.lease_owner = worker_id
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            document = self._documents[job.document_id]
            version = self._versions[job.document_version_id]
            document.status = DocumentStatus.PROCESSING
            document.updated_at = now
            version.status = DocumentStatus.PROCESSING
            return _copy(job)

    async def update_job_stage(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        stage: IngestionStage,
        lease_seconds: int,
    ) -> IngestionJob:
        now = utc_now()
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError("ingestion job not found")
            if job.status != JobStatus.RUNNING or job.lease_owner != worker_id:
                raise ConflictError("ingestion job lease is not owned by this worker")
            job.stage = stage
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            return _copy(job)

    async def complete_ingestion(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        chunks: list[Chunk],
    ) -> int:
        now = utc_now()
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError("ingestion job not found")
            if job.status != JobStatus.RUNNING or job.lease_owner != worker_id:
                raise ConflictError("ingestion job lease is not owned by this worker")
            if any(chunk.document_version_id != job.document_version_id for chunk in chunks):
                raise ConflictError("chunk belongs to a different document version")
            stale_chunk_ids = [
                chunk_id
                for chunk_id, chunk in self._chunks.items()
                if chunk.document_version_id == job.document_version_id
            ]
            for chunk_id in stale_chunk_ids:
                self._chunks.pop(chunk_id, None)
            self._chunks.update({_chunk.id: _copy(_chunk) for _chunk in chunks})
            job.status = JobStatus.COMPLETED
            job.stage = IngestionStage.READY
            job.lease_owner = None
            job.lease_until = None
            job.error_code = None
            job.error_message = None
            job.updated_at = now
            job.completed_at = now
            document = self._documents[job.document_id]
            version = self._versions[job.document_version_id]
            document.status = DocumentStatus.READY
            document.updated_at = now
            version.status = DocumentStatus.READY
            revision = self._revisions.get(job.workspace_id, 0) + 1
            self._revisions[job.workspace_id] = revision
            return revision

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        error_message: str,
        retry_at: datetime,
    ) -> IngestionJob:
        now = utc_now()
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise NotFoundError("ingestion job not found")
            if job.status != JobStatus.RUNNING or job.lease_owner != worker_id:
                raise ConflictError("ingestion job lease is not owned by this worker")
            terminal = job.attempt >= job.max_attempts
            job.status = JobStatus.FAILED if terminal else JobStatus.RETRYING
            job.stage = IngestionStage.FAILED
            job.lease_owner = None
            job.lease_until = None
            job.next_attempt_at = retry_at
            job.error_code = error_code
            job.error_message = error_message[:2000]
            job.updated_at = now
            if terminal:
                self._documents[job.document_id].status = DocumentStatus.FAILED
                self._documents[job.document_id].updated_at = now
                self._versions[job.document_version_id].status = DocumentStatus.FAILED
            return _copy(job)

    async def get_corpus_revision(self, workspace_id: str) -> int:
        async with self._lock:
            return self._revisions.get(workspace_id, 0)

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
    ) -> list[RetrievedChunk]:
        document_filter = set(document_ids)
        query_terms = Counter(term.lower() for term in _TERM_PATTERN.findall(query))
        async with self._lock:
            chunks = [
                _copy(chunk)
                for chunk in self._chunks.values()
                if chunk.workspace_id == workspace_id
                and (not document_filter or chunk.document_id in document_filter)
            ]
            titles = {item.id: item.title for item in self._documents.values()}

        dense_ranked = sorted(
            chunks,
            key=lambda chunk: self._cosine(query_embedding, chunk.embedding),
            reverse=True,
        )[:candidate_pool]
        sparse_ranked = sorted(
            chunks,
            key=lambda chunk: self._sparse_score(query_terms, chunk.text),
            reverse=True,
        )[:candidate_pool]
        dense_ranks = {chunk.id: rank for rank, chunk in enumerate(dense_ranked, start=1)}
        sparse_ranks = {chunk.id: rank for rank, chunk in enumerate(sparse_ranked, start=1)}
        by_id = {chunk.id: chunk for chunk in chunks}
        scored: list[tuple[float, Chunk]] = []
        for chunk_id in dense_ranks.keys() | sparse_ranks.keys():
            dense_component = dense_weight / (60 + dense_ranks.get(chunk_id, candidate_pool + 1))
            sparse_component = sparse_weight / (60 + sparse_ranks.get(chunk_id, candidate_pool + 1))
            scored.append((dense_component + sparse_component, by_id[chunk_id]))
        scored.sort(key=lambda item: (-item[0], item[1].ordinal, str(item[1].id)))
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                workspace_id=chunk.workspace_id,
                document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,
                document_title=titles.get(chunk.document_id, "Untitled document"),
                chunk_ordinal=chunk.ordinal,
                text=chunk.text,
                locator=chunk.locator,
                score=score,
                dense_score=self._cosine(query_embedding, chunk.embedding),
                sparse_score=self._sparse_score(query_terms, chunk.text),
            )
            for score, chunk in scored[:top_k]
        ]

    async def get_chunks(self, chunk_ids: list[UUID]) -> list[Chunk]:
        async with self._lock:
            chunks = [self._chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self._chunks]
            return [_copy(chunk) for chunk in chunks]

    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        async with self._lock:
            if run.id in self._runs:
                raise ConflictError("workflow run already exists")
            self._runs[run.id] = _copy(run)
            return _copy(run)

    async def save_run(self, run: WorkflowRun) -> WorkflowRun:
        async with self._lock:
            if run.id not in self._runs:
                raise NotFoundError("workflow run not found")
            self._runs[run.id] = _copy(run)
            return _copy(run)

    async def get_run(self, run_id: UUID) -> WorkflowRun:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise NotFoundError("workflow run not found", details={"run_id": str(run_id)})
            return _copy(run)

    async def list_runs(
        self,
        *,
        workspace_id: str,
        workflow: WorkflowType | None,
        limit: int,
    ) -> list[WorkflowRun]:
        async with self._lock:
            runs = [
                _copy(run)
                for run in self._runs.values()
                if run.workspace_id == workspace_id
                and (workflow is None or run.workflow == workflow)
            ]
        return sorted(runs, key=lambda item: item.created_at, reverse=True)[:limit]

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)

    @staticmethod
    def _sparse_score(query_terms: Counter[str], text: str) -> float:
        if not query_terms:
            return 0.0
        document_terms = Counter(term.lower() for term in _TERM_PATTERN.findall(text))
        matched = sum(
            min(count, document_terms.get(term, 0)) for term, count in query_terms.items()
        )
        return matched / sum(query_terms.values())
