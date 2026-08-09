"""PostgreSQL and pgvector repository implementation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import asyncpg

from agentflow.domain import (
    Chunk,
    Citation,
    Document,
    DocumentStatus,
    DocumentVersion,
    IngestionJob,
    IngestionStage,
    JobStatus,
    RetrievedChunk,
    RunStatus,
    RunStep,
    UploadRecord,
    WorkflowRun,
    WorkflowType,
)
from agentflow.errors import ConflictError, DependencyUnavailableError, NotFoundError


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(value, ".10g") for value in values) + "]"


def _parse_vector(value: Any) -> list[float]:
    if isinstance(value, str):
        stripped = value.strip("[]")
        return [float(part) for part in stripped.split(",") if part]
    return [float(part) for part in value]


class PostgresRepository:
    def __init__(
        self,
        *,
        dsn: str,
        min_size: int = 1,
        max_size: int = 10,
        command_timeout_seconds: float = 30,
    ) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._command_timeout = command_timeout_seconds
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise DependencyUnavailableError("PostgreSQL repository has not started")
        return self._pool

    async def start(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                command_timeout=self._command_timeout,
            )
        except (OSError, asyncpg.PostgresError) as exc:
            raise DependencyUnavailableError("PostgreSQL connection failed") from exc

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ping(self) -> bool:
        try:
            return bool(await self.pool.fetchval("SELECT true"))
        except (DependencyUnavailableError, asyncpg.PostgresError, OSError):
            return False

    async def create_upload(
        self,
        *,
        document: Document,
        version: DocumentVersion,
        job: IngestionJob,
    ) -> UploadRecord:
        async with self.pool.acquire() as connection, connection.transaction():
            existing = await connection.fetchrow(
                "SELECT id, document_id, document_version_id FROM ingestion_jobs "
                "WHERE idempotency_key = $1",
                job.idempotency_key,
            )
            if existing is not None:
                existing_job = await connection.fetchrow(
                    "SELECT * FROM ingestion_jobs WHERE id = $1",
                    existing["id"],
                )
                existing_document = await connection.fetchrow(
                    "SELECT * FROM documents WHERE id = $1",
                    existing["document_id"],
                )
                existing_version = await connection.fetchrow(
                    "SELECT * FROM document_versions WHERE id = $1",
                    existing["document_version_id"],
                )
                return UploadRecord(
                    document=self._document(existing_document),
                    version=self._version(existing_version),
                    job=self._job(existing_job),
                    created=False,
                )
            try:
                await connection.execute(
                    """
                    INSERT INTO documents
                        (id, workspace_id, title, filename, media_type, status,
                         latest_version_id, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NULL, $7, $8)
                    """,
                    document.id,
                    document.workspace_id,
                    document.title,
                    document.filename,
                    document.media_type,
                    document.status.value,
                    document.created_at,
                    document.updated_at,
                )
                await connection.execute(
                    """
                    INSERT INTO document_versions
                        (id, document_id, workspace_id, version_number, content_sha256,
                         object_key, object_version_id, size_bytes, media_type, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    version.id,
                    version.document_id,
                    version.workspace_id,
                    version.version_number,
                    version.content_sha256,
                    version.object_key,
                    version.object_version_id,
                    version.size_bytes,
                    version.media_type,
                    version.status.value,
                    version.created_at,
                )
                await connection.execute(
                    "UPDATE documents SET latest_version_id = $2 WHERE id = $1",
                    document.id,
                    version.id,
                )
                await connection.execute(
                    """
                    INSERT INTO ingestion_jobs
                        (id, workspace_id, document_id, document_version_id, idempotency_key,
                         status, stage, attempt, max_attempts, lease_owner, lease_until,
                         next_attempt_at, error_code, error_message, created_at, updated_at,
                         completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                            $12, $13, $14, $15, $16, $17)
                    """,
                    job.id,
                    job.workspace_id,
                    job.document_id,
                    job.document_version_id,
                    job.idempotency_key,
                    job.status.value,
                    job.stage.value,
                    job.attempt,
                    job.max_attempts,
                    job.lease_owner,
                    job.lease_until,
                    job.next_attempt_at,
                    job.error_code,
                    job.error_message,
                    job.created_at,
                    job.updated_at,
                    job.completed_at,
                )
                await connection.execute(
                    "INSERT INTO corpus_state (workspace_id) VALUES ($1) "
                    "ON CONFLICT (workspace_id) DO NOTHING",
                    document.workspace_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise ConflictError("upload conflicts with an existing record") from exc
        document.latest_version_id = version.id
        return UploadRecord(document=document, version=version, job=job)

    async def find_upload_by_idempotency(self, idempotency_key: str) -> UploadRecord | None:
        row = await self.pool.fetchrow(
            """
            SELECT j.id AS job_lookup_id, j.document_id AS job_document_id,
                   j.document_version_id AS job_version_id
            FROM ingestion_jobs j
            WHERE j.idempotency_key = $1
            """,
            idempotency_key,
        )
        if row is None:
            return None
        job_row = await self.pool.fetchrow(
            "SELECT * FROM ingestion_jobs WHERE id = $1",
            row["job_lookup_id"],
        )
        document_row = await self.pool.fetchrow(
            "SELECT * FROM documents WHERE id = $1",
            row["job_document_id"],
        )
        version_row = await self.pool.fetchrow(
            "SELECT * FROM document_versions WHERE id = $1",
            row["job_version_id"],
        )
        if job_row is None or document_row is None or version_row is None:
            raise DependencyUnavailableError("upload records are inconsistent")
        return UploadRecord(
            document=self._document(document_row),
            version=self._version(version_row),
            job=self._job(job_row),
            created=False,
        )

    async def get_document(self, document_id: UUID) -> Document:
        row = await self.pool.fetchrow("SELECT * FROM documents WHERE id = $1", document_id)
        if row is None:
            raise NotFoundError("document not found", details={"document_id": str(document_id)})
        return self._document(row)

    async def list_documents(self, workspace_id: str) -> list[Document]:
        rows = await self.pool.fetch(
            "SELECT * FROM documents WHERE workspace_id = $1 ORDER BY created_at DESC",
            workspace_id,
        )
        return [self._document(row) for row in rows]

    async def get_document_version(self, version_id: UUID) -> DocumentVersion:
        row = await self.pool.fetchrow(
            "SELECT * FROM document_versions WHERE id = $1",
            version_id,
        )
        if row is None:
            raise NotFoundError(
                "document version not found",
                details={"version_id": str(version_id)},
            )
        return self._version(row)

    async def get_job(self, job_id: UUID) -> IngestionJob:
        row = await self.pool.fetchrow("SELECT * FROM ingestion_jobs WHERE id = $1", job_id)
        if row is None:
            raise NotFoundError("ingestion job not found", details={"job_id": str(job_id)})
        return self._job(row)

    async def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> IngestionJob | None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """
                WITH terminalized AS (
                    UPDATE ingestion_jobs
                    SET status = 'failed',
                        stage = 'failed',
                        lease_owner = NULL,
                        lease_until = NULL,
                        error_code = 'lease_expired',
                        error_message = 'worker lease expired after final attempt',
                        updated_at = now(),
                        completed_at = now()
                    WHERE status = 'running'
                      AND lease_until <= now()
                      AND attempt >= max_attempts
                    RETURNING document_id, document_version_id
                ),
                failed_documents AS (
                    UPDATE documents AS document
                    SET status = 'failed', updated_at = now()
                    FROM terminalized
                    WHERE document.id = terminalized.document_id
                      AND document.latest_version_id = terminalized.document_version_id
                    RETURNING document.id
                )
                UPDATE document_versions AS version
                SET status = 'failed'
                FROM terminalized
                WHERE version.id = terminalized.document_version_id
                """
            )
            row = await connection.fetchrow(
                """
                WITH candidate AS (
                    SELECT id
                    FROM ingestion_jobs
                    WHERE attempt < max_attempts
                      AND (
                        (status IN ('pending', 'retrying') AND next_attempt_at <= now())
                        OR (status = 'running' AND lease_until <= now())
                      )
                    ORDER BY next_attempt_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE ingestion_jobs AS job
                SET status = 'running',
                    stage = 'downloading',
                    attempt = job.attempt + 1,
                    lease_owner = $1,
                    lease_until = now() + make_interval(secs => $2),
                    updated_at = now()
                FROM candidate
                WHERE job.id = candidate.id
                RETURNING job.*
                """,
                worker_id,
                lease_seconds,
            )
            if row is None:
                return None
            await connection.execute(
                "UPDATE documents SET status = 'processing', updated_at = now() WHERE id = $1",
                row["document_id"],
            )
            await connection.execute(
                "UPDATE document_versions SET status = 'processing' WHERE id = $1",
                row["document_version_id"],
            )
            return self._job(row)

    async def update_job_stage(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        stage: IngestionStage,
        lease_seconds: int,
    ) -> IngestionJob:
        row = await self.pool.fetchrow(
            """
            UPDATE ingestion_jobs
            SET stage = $3,
                lease_until = now() + make_interval(secs => $4),
                updated_at = now()
            WHERE id = $1 AND status = 'running' AND lease_owner = $2
            RETURNING *
            """,
            job_id,
            worker_id,
            stage.value,
            lease_seconds,
        )
        if row is None:
            raise ConflictError("ingestion job lease is not owned by this worker")
        return self._job(row)

    async def complete_ingestion(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        chunks: list[Chunk],
    ) -> int:
        async with self.pool.acquire() as connection, connection.transaction():
            job_row = await connection.fetchrow(
                "SELECT * FROM ingestion_jobs WHERE id = $1 FOR UPDATE",
                job_id,
            )
            if job_row is None:
                raise NotFoundError("ingestion job not found")
            if job_row["status"] != JobStatus.RUNNING.value or job_row["lease_owner"] != worker_id:
                raise ConflictError("ingestion job lease is not owned by this worker")
            if any(chunk.document_version_id != job_row["document_version_id"] for chunk in chunks):
                raise ConflictError("chunk belongs to a different document version")
            await connection.execute(
                "DELETE FROM chunks WHERE document_version_id = $1",
                job_row["document_version_id"],
            )
            if chunks:
                await connection.executemany(
                    """
                    INSERT INTO chunks
                        (id, workspace_id, document_id, document_version_id, ordinal, text,
                         token_count, embedding, locator, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9::jsonb, $10::jsonb, $11)
                    """,
                    [
                        (
                            chunk.id,
                            chunk.workspace_id,
                            chunk.document_id,
                            chunk.document_version_id,
                            chunk.ordinal,
                            chunk.text,
                            chunk.token_count,
                            _vector_literal(chunk.embedding),
                            json.dumps(chunk.locator),
                            json.dumps(chunk.metadata),
                            chunk.created_at,
                        )
                        for chunk in chunks
                    ],
                )
            updated = await connection.fetchrow(
                """
                UPDATE ingestion_jobs
                SET status = 'completed', stage = 'ready', lease_owner = NULL,
                    lease_until = NULL, error_code = NULL, error_message = NULL,
                    updated_at = now(), completed_at = now()
                WHERE id = $1 AND status = 'running' AND lease_owner = $2
                RETURNING *
                """,
                job_id,
                worker_id,
            )
            if updated is None:
                raise ConflictError("ingestion job lease was lost")
            await connection.execute(
                "UPDATE documents SET status = 'ready', updated_at = now() WHERE id = $1",
                job_row["document_id"],
            )
            await connection.execute(
                "UPDATE document_versions SET status = 'ready' WHERE id = $1",
                job_row["document_version_id"],
            )
            revision = await connection.fetchval(
                """
                INSERT INTO corpus_state (workspace_id, revision, updated_at)
                VALUES ($1, 1, now())
                ON CONFLICT (workspace_id) DO UPDATE
                SET revision = corpus_state.revision + 1, updated_at = now()
                RETURNING revision
                """,
                job_row["workspace_id"],
            )
            return int(revision)

    async def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_code: str,
        error_message: str,
        retry_at: datetime,
    ) -> IngestionJob:
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE ingestion_jobs
                SET status = CASE WHEN attempt >= max_attempts THEN 'failed' ELSE 'retrying' END,
                    stage = 'failed', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = $5, error_code = $3, error_message = $4,
                    updated_at = now()
                WHERE id = $1 AND status = 'running' AND lease_owner = $2
                RETURNING *
                """,
                job_id,
                worker_id,
                error_code,
                error_message[:2000],
                retry_at,
            )
            if row is None:
                raise ConflictError("ingestion job lease is not owned by this worker")
            if row["status"] == JobStatus.FAILED.value:
                await connection.execute(
                    "UPDATE documents SET status = 'failed', updated_at = now() WHERE id = $1",
                    row["document_id"],
                )
                await connection.execute(
                    "UPDATE document_versions SET status = 'failed' WHERE id = $1",
                    row["document_version_id"],
                )
            return self._job(row)

    async def get_corpus_revision(self, workspace_id: str) -> int:
        value = await self.pool.fetchval(
            "SELECT revision FROM corpus_state WHERE workspace_id = $1",
            workspace_id,
        )
        return int(value or 0)

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
        rows = await self.pool.fetch(
            """
            WITH eligible AS (
                SELECT c.id, c.workspace_id, c.document_id, c.document_version_id,
                       c.ordinal, c.text, c.locator, d.title AS document_title,
                       1 - (c.embedding <=> $2::vector) AS dense_score,
                       ts_rank_cd(c.search_vector, plainto_tsquery('english', $3)) AS sparse_score
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.workspace_id = $1
                  AND ($4::uuid[] IS NULL OR c.document_id = ANY($4::uuid[]))
            ),
            dense AS (
                SELECT id, row_number() OVER (ORDER BY dense_score DESC, id) AS rank
                FROM eligible
                ORDER BY dense_score DESC, id
                LIMIT $5
            ),
            sparse AS (
                SELECT id, row_number() OVER (ORDER BY sparse_score DESC, id) AS rank
                FROM eligible
                ORDER BY sparse_score DESC, id
                LIMIT $5
            )
            SELECT e.*,
                   COALESCE($6 / (60 + dense.rank), 0) +
                   COALESCE($7 / (60 + sparse.rank), 0) AS combined_score
            FROM eligible e
            LEFT JOIN dense ON dense.id = e.id
            LEFT JOIN sparse ON sparse.id = e.id
            WHERE dense.id IS NOT NULL OR sparse.id IS NOT NULL
            ORDER BY combined_score DESC, e.ordinal, e.id
            LIMIT $8
            """,
            workspace_id,
            _vector_literal(query_embedding),
            query,
            document_ids or None,
            candidate_pool,
            dense_weight,
            sparse_weight,
            top_k,
        )
        return [
            RetrievedChunk(
                chunk_id=row["id"],
                workspace_id=row["workspace_id"],
                document_id=row["document_id"],
                document_version_id=row["document_version_id"],
                document_title=row["document_title"],
                chunk_ordinal=row["ordinal"],
                text=row["text"],
                locator=_json_value(row["locator"]),
                score=float(row["combined_score"]),
                dense_score=float(row["dense_score"]),
                sparse_score=float(row["sparse_score"]),
            )
            for row in rows
        ]

    async def get_chunks(self, chunk_ids: list[UUID]) -> list[Chunk]:
        if not chunk_ids:
            return []
        rows = await self.pool.fetch(
            "SELECT *, embedding::text AS embedding_text FROM chunks WHERE id = ANY($1::uuid[])",
            chunk_ids,
        )
        by_id = {row["id"]: self._chunk(row) for row in rows}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    async def create_run(self, run: WorkflowRun) -> WorkflowRun:
        try:
            await self.pool.execute(
                """
                INSERT INTO workflow_runs
                    (id, workspace_id, workflow, status, corpus_revision, normalized_input,
                     document_ids, model_id, prompt_version, graph_version, cached, result,
                     evidence_gap, steps, metrics, error_code, error_message, created_at,
                     completed_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11,
                        $12::jsonb, $13, $14::jsonb, $15::jsonb, $16, $17, $18, $19)
                """,
                run.id,
                run.workspace_id,
                run.workflow.value,
                run.status.value,
                run.corpus_revision,
                json.dumps(run.normalized_input, default=str),
                run.document_ids,
                run.model_id,
                run.prompt_version,
                run.graph_version,
                run.cached,
                json.dumps(run.result, default=str) if run.result is not None else None,
                run.evidence_gap,
                json.dumps([step.model_dump(mode="json") for step in run.steps]),
                json.dumps(run.metrics, default=str),
                run.error_code,
                run.error_message,
                run.created_at,
                run.completed_at,
            )
        except asyncpg.UniqueViolationError as exc:
            raise ConflictError("workflow run already exists") from exc
        return run

    async def save_run(self, run: WorkflowRun) -> WorkflowRun:
        async with self.pool.acquire() as connection, connection.transaction():
            result = await connection.execute(
                """
                UPDATE workflow_runs
                SET status = $2, cached = $3, result = $4::jsonb, evidence_gap = $5,
                    steps = $6::jsonb, metrics = $7::jsonb, error_code = $8,
                    error_message = $9, completed_at = $10
                WHERE id = $1
                """,
                run.id,
                run.status.value,
                run.cached,
                json.dumps(run.result, default=str) if run.result is not None else None,
                run.evidence_gap,
                json.dumps([step.model_dump(mode="json") for step in run.steps]),
                json.dumps(run.metrics, default=str),
                run.error_code,
                run.error_message,
                run.completed_at,
            )
            if result.endswith("0"):
                raise NotFoundError("workflow run not found")
            await connection.execute("DELETE FROM citations WHERE run_id = $1", run.id)
            if run.citations:
                await connection.executemany(
                    """
                    INSERT INTO citations
                        (id, run_id, chunk_id, document_id, document_version_id,
                         document_title, chunk_ordinal, quote, locator, score)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                    """,
                    [
                        (
                            citation.citation_id,
                            run.id,
                            citation.chunk_id,
                            citation.document_id,
                            citation.document_version_id,
                            citation.document_title,
                            citation.chunk_ordinal,
                            citation.quote,
                            json.dumps(citation.locator),
                            citation.score,
                        )
                        for citation in run.citations
                    ],
                )
        return run

    async def get_run(self, run_id: UUID) -> WorkflowRun:
        row = await self.pool.fetchrow("SELECT * FROM workflow_runs WHERE id = $1", run_id)
        if row is None:
            raise NotFoundError("workflow run not found", details={"run_id": str(run_id)})
        citations = await self._citations_for_runs([run_id])
        return self._run(row, citations.get(run_id, []))

    async def list_runs(
        self,
        *,
        workspace_id: str,
        workflow: WorkflowType | None,
        limit: int,
    ) -> list[WorkflowRun]:
        rows = await self.pool.fetch(
            """
            SELECT * FROM workflow_runs
            WHERE workspace_id = $1 AND ($2::text IS NULL OR workflow = $2)
            ORDER BY created_at DESC
            LIMIT $3
            """,
            workspace_id,
            workflow.value if workflow else None,
            limit,
        )
        citations = await self._citations_for_runs([row["id"] for row in rows])
        return [self._run(row, citations.get(row["id"], [])) for row in rows]

    async def _citations_for_runs(self, run_ids: list[UUID]) -> dict[UUID, list[Citation]]:
        if not run_ids:
            return {}
        rows = await self.pool.fetch(
            "SELECT * FROM citations WHERE run_id = ANY($1::uuid[]) ORDER BY created_at, id",
            run_ids,
        )
        result: dict[UUID, list[Citation]] = {}
        for row in rows:
            result.setdefault(row["run_id"], []).append(self._citation(row))
        return result

    @staticmethod
    def _document(row: Mapping[str, Any]) -> Document:
        return Document(
            id=row["id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            filename=row["filename"],
            media_type=row["media_type"],
            status=DocumentStatus(row["status"]),
            latest_version_id=row["latest_version_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _version(row: Mapping[str, Any]) -> DocumentVersion:
        return DocumentVersion(
            id=row["id"],
            document_id=row["document_id"],
            workspace_id=row["workspace_id"],
            version_number=row["version_number"],
            content_sha256=row["content_sha256"],
            object_key=row["object_key"],
            object_version_id=row["object_version_id"],
            size_bytes=row["size_bytes"],
            media_type=row["media_type"],
            status=DocumentStatus(row["status"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _job(row: Mapping[str, Any]) -> IngestionJob:
        return IngestionJob(
            id=row["id"],
            workspace_id=row["workspace_id"],
            document_id=row["document_id"],
            document_version_id=row["document_version_id"],
            idempotency_key=row["idempotency_key"],
            status=JobStatus(row["status"]),
            stage=IngestionStage(row["stage"]),
            attempt=row["attempt"],
            max_attempts=row["max_attempts"],
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            next_attempt_at=row["next_attempt_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _chunk(row: Mapping[str, Any]) -> Chunk:
        return Chunk(
            id=row["id"],
            workspace_id=row["workspace_id"],
            document_id=row["document_id"],
            document_version_id=row["document_version_id"],
            ordinal=row["ordinal"],
            text=row["text"],
            token_count=row["token_count"],
            embedding=_parse_vector(row["embedding_text"]),
            locator=_json_value(row["locator"]),
            metadata=_json_value(row["metadata"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _citation(row: Mapping[str, Any]) -> Citation:
        return Citation(
            citation_id=row["id"],
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_version_id=row["document_version_id"],
            document_title=row["document_title"],
            chunk_ordinal=row["chunk_ordinal"],
            quote=row["quote"],
            locator=_json_value(row["locator"]),
            score=row["score"],
        )

    @staticmethod
    def _run(row: Mapping[str, Any], citations: list[Citation]) -> WorkflowRun:
        step_values = cast(list[dict[str, Any]], _json_value(row["steps"]))
        return WorkflowRun(
            id=row["id"],
            workspace_id=row["workspace_id"],
            workflow=WorkflowType(row["workflow"]),
            status=RunStatus(row["status"]),
            corpus_revision=row["corpus_revision"],
            normalized_input=_json_value(row["normalized_input"]),
            document_ids=list(row["document_ids"]),
            model_id=row["model_id"],
            prompt_version=row["prompt_version"],
            graph_version=row["graph_version"],
            cached=row["cached"],
            result=_json_value(row["result"]) if row["result"] is not None else None,
            citations=citations,
            evidence_gap=row["evidence_gap"],
            steps=[RunStep.model_validate(item) for item in step_values],
            metrics=_json_value(row["metrics"]),
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
