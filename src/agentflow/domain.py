"""Typed domain models used across AgentFlow boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionStage(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class WorkflowType(StrEnum):
    QUESTION = "question"
    COMPARE = "compare"
    BRIEF = "brief"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    EVIDENCE_GAP = "evidence_gap"
    FAILED = "failed"


class Document(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    title: str
    filename: str
    media_type: str
    status: DocumentStatus = DocumentStatus.PENDING
    latest_version_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentVersion(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    workspace_id: str
    version_number: int = 1
    content_sha256: str
    object_key: str
    object_version_id: str | None = Field(default=None, min_length=1)
    size_bytes: int
    media_type: str
    status: DocumentStatus = DocumentStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("object_version_id")
    @classmethod
    def _validate_object_version_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("object_version_id must be nonempty when provided")
        return normalized


class Chunk(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    document_id: UUID
    document_version_id: UUID
    ordinal: int = Field(ge=0)
    text: str
    token_count: int = Field(ge=0)
    embedding: list[float]
    locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class IngestionJob(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    document_id: UUID
    document_version_id: UUID
    idempotency_key: str
    status: JobStatus = JobStatus.PENDING
    stage: IngestionStage = IngestionStage.PENDING
    attempt: int = 0
    max_attempts: int = 4
    lease_owner: str | None = None
    lease_until: datetime | None = None
    next_attempt_at: datetime = Field(default_factory=utc_now)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class RetrievedChunk(DomainModel):
    chunk_id: UUID
    workspace_id: str
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_ordinal: int
    text: str
    locator: dict[str, Any] = Field(default_factory=dict)
    score: float
    dense_score: float = 0.0
    sparse_score: float = 0.0


class Citation(DomainModel):
    citation_id: UUID = Field(default_factory=uuid4)
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_ordinal: int
    quote: str
    locator: dict[str, Any] = Field(default_factory=dict)
    score: float


class RunStep(DomainModel):
    name: str
    status: str = "completed"
    latency_ms: float = Field(default=0, ge=0)
    detail: dict[str, Any] = Field(default_factory=dict)


class ProviderUsage(DomainModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    generation_calls: int = Field(default=0, ge=0)


class ProviderResponse(DomainModel):
    text: str
    structured: dict[str, Any]
    citation_indices: list[int]
    model_id: str
    usage: ProviderUsage = Field(default_factory=ProviderUsage)


class WorkflowRun(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    workflow: WorkflowType
    status: RunStatus = RunStatus.RUNNING
    corpus_revision: int
    normalized_input: dict[str, Any]
    document_ids: list[UUID] = Field(default_factory=list)
    model_id: str
    prompt_version: str
    graph_version: str
    cached: bool = False
    result: dict[str, Any] | None = None
    citations: list[Citation] = Field(default_factory=list)
    evidence_gap: str | None = None
    steps: list[RunStep] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class UploadRecord(DomainModel):
    document: Document
    version: DocumentVersion
    job: IngestionJob
    created: bool = True


class WorkflowExecution(DomainModel):
    result: dict[str, Any]
    citations: list[Citation]
    cached: bool
    verified: bool
    evidence_gap: str | None = None
    steps: list[RunStep] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
