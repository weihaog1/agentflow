"""Idempotent upload registration and worker-owned document ingestion."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import structlog

from agentflow.domain import (
    Chunk,
    Document,
    DocumentVersion,
    IngestionJob,
    IngestionStage,
    UploadRecord,
    utc_now,
)
from agentflow.errors import AgentFlowError, UnsafeDocumentError, ValidationError
from agentflow.extraction import DocumentExtractor, TextChunker
from agentflow.metrics import INGESTION_JOBS, INGESTION_STAGE_DURATION
from agentflow.object_store.base import ObjectStore
from agentflow.providers.base import EmbeddingProvider
from agentflow.repositories.base import Repository

logger = structlog.get_logger(__name__)
_WORKSPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MEDIA_BY_EXTENSION = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class IngestionService:
    def __init__(
        self,
        *,
        repository: Repository,
        object_store: ObjectStore,
        extractor: DocumentExtractor,
        chunker: TextChunker,
        embedding_provider: EmbeddingProvider,
        embedding_batch_size: int,
        worker_lease_seconds: int,
        max_attempts: int,
    ) -> None:
        self._repository = repository
        self._store = object_store
        self._extractor = extractor
        self._chunker = chunker
        self._embeddings = embedding_provider
        self._batch_size = embedding_batch_size
        self._lease_seconds = worker_lease_seconds
        self._max_attempts = max_attempts

    async def register_upload(
        self,
        *,
        workspace_id: str,
        filename: str,
        media_type: str,
        data: bytes,
        title: str | None = None,
    ) -> UploadRecord:
        workspace = self._validate_workspace(workspace_id)
        safe_filename, safe_media_type = self._extractor.validate(
            filename=filename,
            media_type=media_type,
            data=data,
        )
        content_sha256 = hashlib.sha256(data).hexdigest()
        idempotency_key = hashlib.sha256(
            f"upload:{workspace}:{safe_filename}:{content_sha256}".encode()
        ).hexdigest()
        document_id = uuid5(NAMESPACE_URL, f"agentflow:{idempotency_key}:document")
        version_id = uuid5(NAMESPACE_URL, f"agentflow:{idempotency_key}:version")
        job_id = uuid5(NAMESPACE_URL, f"agentflow:{idempotency_key}:job")
        object_key = f"managed/{workspace}/{document_id}/{version_id}/{content_sha256}"
        now = utc_now()
        document = Document(
            id=document_id,
            workspace_id=workspace,
            title=self._normalize_title(title or Path(safe_filename).stem),
            filename=safe_filename,
            media_type=safe_media_type,
            latest_version_id=version_id,
            created_at=now,
            updated_at=now,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            workspace_id=workspace,
            content_sha256=content_sha256,
            object_key=object_key,
            size_bytes=len(data),
            media_type=safe_media_type,
            created_at=now,
        )
        job = IngestionJob(
            id=job_id,
            workspace_id=workspace,
            document_id=document_id,
            document_version_id=version_id,
            idempotency_key=idempotency_key,
            max_attempts=self._max_attempts,
            created_at=now,
            updated_at=now,
            next_attempt_at=now,
        )
        existing = await self._repository.find_upload_by_idempotency(idempotency_key)
        if existing is not None:
            return existing
        stored = await self._store.put(
            object_key,
            data,
            content_type=safe_media_type,
            checksum_sha256=content_sha256,
        )
        version.object_version_id = stored.version_id
        try:
            return await self._repository.create_upload(document=document, version=version, job=job)
        except Exception:
            try:
                existing = await self._repository.find_upload_by_idempotency(idempotency_key)
            except Exception:
                existing = None
            if existing is not None:
                return existing
            await self._store.delete(object_key, version_id=stored.version_id)
            raise

    async def register_existing_object(
        self,
        *,
        workspace_id: str,
        object_key: str,
        idempotency_key: str,
        expected_size_bytes: int,
        object_version_id: str | None = None,
    ) -> UploadRecord:
        """Register a Lambda-validated S3 object as a durable PostgreSQL job."""

        workspace = self._validate_workspace(workspace_id)
        data = await self._store.get(object_key, version_id=object_version_id)
        if len(data) != expected_size_bytes:
            raise UnsafeDocumentError("S3 event size does not match the stored object")
        filename = Path(object_key).name
        extension = Path(filename).suffix.lower()
        media_type = _MEDIA_BY_EXTENSION.get(extension, "application/octet-stream")
        safe_filename, safe_media_type = self._extractor.validate(
            filename=filename,
            media_type=media_type,
            data=data,
        )
        content_sha256 = hashlib.sha256(data).hexdigest()
        document_id = uuid5(NAMESPACE_URL, f"agentflow:s3:{idempotency_key}:document")
        version_id = uuid5(NAMESPACE_URL, f"agentflow:s3:{idempotency_key}:version")
        job_id = uuid5(NAMESPACE_URL, f"agentflow:s3:{idempotency_key}:job")
        now = utc_now()
        document = Document(
            id=document_id,
            workspace_id=workspace,
            title=self._normalize_title(Path(safe_filename).stem),
            filename=safe_filename,
            media_type=safe_media_type,
            latest_version_id=version_id,
            created_at=now,
            updated_at=now,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            workspace_id=workspace,
            content_sha256=content_sha256,
            object_key=object_key,
            object_version_id=object_version_id,
            size_bytes=len(data),
            media_type=safe_media_type,
            created_at=now,
        )
        job = IngestionJob(
            id=job_id,
            workspace_id=workspace,
            document_id=document_id,
            document_version_id=version_id,
            idempotency_key=f"s3:{idempotency_key}",
            max_attempts=self._max_attempts,
            created_at=now,
            updated_at=now,
            next_attempt_at=now,
        )
        return await self._repository.create_upload(document=document, version=version, job=job)

    async def process(self, job: IngestionJob, *, worker_id: str) -> int | None:
        try:
            return await self._process(job, worker_id=worker_id)
        except Exception as exc:
            error_code = exc.code if isinstance(exc, AgentFlowError) else "ingestion_internal_error"
            message = (
                str(exc) if isinstance(exc, AgentFlowError) else "unexpected ingestion failure"
            )
            retry_delay = min(2 ** max(job.attempt, 1), 60)
            await self._repository.fail_job(
                job_id=job.id,
                worker_id=worker_id,
                error_code=error_code,
                error_message=message,
                retry_at=utc_now() + timedelta(seconds=retry_delay),
            )
            INGESTION_JOBS.labels(outcome="failed_attempt").inc()
            logger.exception(
                "ingestion_job_failed",
                job_id=str(job.id),
                document_id=str(job.document_id),
                attempt=job.attempt,
                error_code=error_code,
            )
            return None

    async def _process(self, job: IngestionJob, *, worker_id: str) -> int:
        version = await self._repository.get_document_version(job.document_version_id)
        document = await self._repository.get_document(job.document_id)
        started = time.perf_counter()
        data = await self._store.get(
            version.object_key,
            version_id=version.object_version_id,
        )
        INGESTION_STAGE_DURATION.labels(stage="downloading").observe(time.perf_counter() - started)
        checksum_mismatch = hashlib.sha256(data).hexdigest() != version.content_sha256
        if len(data) != version.size_bytes or checksum_mismatch:
            raise UnsafeDocumentError("stored document failed size or checksum verification")

        await self._stage(job.id, worker_id, IngestionStage.PARSING)
        started = time.perf_counter()
        extracted = self._extractor.extract(
            filename=document.filename,
            media_type=version.media_type,
            data=data,
        )
        INGESTION_STAGE_DURATION.labels(stage="parsing").observe(time.perf_counter() - started)

        await self._stage(job.id, worker_id, IngestionStage.CHUNKING)
        started = time.perf_counter()
        drafts = self._chunker.chunk(extracted)
        INGESTION_STAGE_DURATION.labels(stage="chunking").observe(time.perf_counter() - started)
        if not drafts:
            raise UnsafeDocumentError("document did not produce any indexable chunks")

        await self._stage(job.id, worker_id, IngestionStage.EMBEDDING)
        started = time.perf_counter()
        embeddings: list[list[float]] = []
        for offset in range(0, len(drafts), self._batch_size):
            batch = drafts[offset : offset + self._batch_size]
            embeddings.extend(await self._embeddings.embed_many([draft.text for draft in batch]))
        if len(embeddings) != len(drafts):
            raise ValidationError("embedding provider returned the wrong number of vectors")
        if any(len(vector) != self._embeddings.dimensions for vector in embeddings):
            raise ValidationError("embedding provider returned the wrong vector dimensions")
        INGESTION_STAGE_DURATION.labels(stage="embedding").observe(time.perf_counter() - started)

        await self._stage(job.id, worker_id, IngestionStage.INDEXING)
        chunks = [
            Chunk(
                id=uuid5(
                    version.id,
                    f"chunk:{draft.ordinal}:{hashlib.sha256(draft.text.encode()).hexdigest()}",
                ),
                workspace_id=job.workspace_id,
                document_id=job.document_id,
                document_version_id=job.document_version_id,
                ordinal=draft.ordinal,
                text=draft.text,
                token_count=draft.token_count,
                embedding=embedding,
                locator=draft.locator,
                metadata={"embedding_model": self._embeddings.identifier},
            )
            for draft, embedding in zip(drafts, embeddings, strict=True)
        ]
        started = time.perf_counter()
        revision = await self._repository.complete_ingestion(
            job_id=job.id,
            worker_id=worker_id,
            chunks=chunks,
        )
        INGESTION_STAGE_DURATION.labels(stage="indexing").observe(time.perf_counter() - started)
        INGESTION_JOBS.labels(outcome="completed").inc()
        logger.info(
            "ingestion_job_completed",
            job_id=str(job.id),
            document_id=str(job.document_id),
            chunk_count=len(chunks),
            corpus_revision=revision,
        )
        return revision

    async def _stage(self, job_id: UUID, worker_id: str, stage: IngestionStage) -> None:
        await self._repository.update_job_stage(
            job_id=job_id,
            worker_id=worker_id,
            stage=stage,
            lease_seconds=self._lease_seconds,
        )

    @staticmethod
    def _validate_workspace(value: str) -> str:
        normalized = value.strip()
        if not _WORKSPACE_PATTERN.fullmatch(normalized):
            raise ValidationError(
                "workspace_id must use letters, numbers, dots, underscores, or hyphens"
            )
        return normalized

    @staticmethod
    def _normalize_title(value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            raise ValidationError("document title cannot be empty")
        return normalized[:300]
