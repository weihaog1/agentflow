"""Public API request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentflow.domain import (
    Citation,
    Document,
    DocumentVersion,
    IngestionJob,
    RunStatus,
    RunStep,
    WorkflowRun,
    WorkflowType,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody


class DocumentUploadResponse(ApiModel):
    document: Document
    version: DocumentVersion
    job: IngestionJob
    created: bool


class DocumentListResponse(ApiModel):
    items: list[Document]
    corpus_revision: int = Field(ge=0)


class QuestionRequest(ApiModel):
    workspace_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    question: str = Field(min_length=1, max_length=20_000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=8, ge=1, le=50)


class CompareRequest(ApiModel):
    workspace_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    document_ids: list[UUID] = Field(min_length=2, max_length=20)
    focus: str | None = Field(default=None, max_length=20_000)
    top_k: int = Field(default=8, ge=1, le=50)


class BriefRequest(ApiModel):
    workspace_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    objective: str | None = Field(default=None, max_length=20_000)
    audience: str | None = Field(default=None, max_length=500)
    max_points: int = Field(default=5, ge=1, le=20)
    top_k: int = Field(default=8, ge=1, le=50)


class WorkflowResponse(ApiModel):
    run_id: UUID
    workspace_id: str
    workflow: WorkflowType
    status: RunStatus
    corpus_revision: int
    cached: bool
    verified: bool
    result: dict[str, Any]
    citations: list[Citation]
    evidence_gap: str | None = None
    steps: list[RunStep]
    metrics: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_run(cls, run: WorkflowRun) -> WorkflowResponse:
        return cls(
            run_id=run.id,
            workspace_id=run.workspace_id,
            workflow=run.workflow,
            status=run.status,
            corpus_revision=run.corpus_revision,
            cached=run.cached,
            verified=run.status == RunStatus.COMPLETED and bool(run.citations),
            result=run.result or {},
            citations=run.citations,
            evidence_gap=run.evidence_gap,
            steps=run.steps,
            metrics=run.metrics,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )


class RunListResponse(ApiModel):
    items: list[WorkflowResponse]
    next_cursor: str | None = None
