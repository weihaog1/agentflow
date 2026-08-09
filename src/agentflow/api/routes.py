"""Versioned API and operational endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse

from agentflow import __version__
from agentflow.api.dependencies import get_container
from agentflow.api.schemas import (
    BriefRequest,
    CompareRequest,
    DocumentListResponse,
    DocumentUploadResponse,
    QuestionRequest,
    RunListResponse,
    WorkflowResponse,
)
from agentflow.container import Container
from agentflow.domain import Document, IngestionJob, WorkflowType
from agentflow.errors import NotFoundError, UnsafeDocumentError
from agentflow.metrics import render_metrics

api_router = APIRouter(prefix="/api/v1")
operations_router = APIRouter()
ContainerDependency = Annotated[Container, Depends(get_container)]


@api_router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    container: ContainerDependency,
    file: Annotated[UploadFile, File()],
    workspace_id: Annotated[str, Form(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")] = "default",
    title: Annotated[str | None, Form(max_length=300)] = None,
) -> DocumentUploadResponse:
    try:
        data = await file.read(container.settings.max_upload_bytes + 1)
    finally:
        await file.close()
    if len(data) > container.settings.max_upload_bytes:
        raise UnsafeDocumentError(
            "document exceeds the upload limit",
            details={"max_bytes": container.settings.max_upload_bytes},
        )
    record = await container.ingestion.register_upload(
        workspace_id=workspace_id,
        filename=file.filename or "upload",
        media_type=file.content_type or "application/octet-stream",
        data=data,
        title=title,
    )
    return DocumentUploadResponse.model_validate(record.model_dump())


@api_router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    container: ContainerDependency,
    workspace_id: Annotated[str, Query(min_length=1, max_length=128)] = "default",
) -> DocumentListResponse:
    documents = await container.repository.list_documents(workspace_id)
    corpus_revision = await container.repository.get_corpus_revision(workspace_id)
    return DocumentListResponse(items=documents, corpus_revision=corpus_revision)


@api_router.get("/documents/{document_id}", response_model=Document)
async def get_document(
    document_id: UUID,
    container: ContainerDependency,
    workspace_id: Annotated[str, Query(min_length=1, max_length=128)] = "default",
) -> Document:
    document = await container.repository.get_document(document_id)
    if document.workspace_id != workspace_id:
        raise NotFoundError("document not found", details={"document_id": str(document_id)})
    return document


@api_router.get("/jobs/{job_id}", response_model=IngestionJob)
async def get_job(
    job_id: UUID,
    container: ContainerDependency,
    workspace_id: Annotated[str, Query(min_length=1, max_length=128)] = "default",
) -> IngestionJob:
    job = await container.repository.get_job(job_id)
    if job.workspace_id != workspace_id:
        raise NotFoundError("ingestion job not found", details={"job_id": str(job_id)})
    return job


@api_router.post("/workflows/question", response_model=WorkflowResponse)
async def question(request: QuestionRequest, container: ContainerDependency) -> WorkflowResponse:
    run = await container.workflows.execute(
        workspace_id=request.workspace_id,
        workflow=WorkflowType.QUESTION,
        raw_input={"question": request.question},
        document_ids=request.document_ids,
        top_k=request.top_k,
    )
    return WorkflowResponse.from_run(run)


@api_router.post("/workflows/compare", response_model=WorkflowResponse)
async def compare(request: CompareRequest, container: ContainerDependency) -> WorkflowResponse:
    run = await container.workflows.execute(
        workspace_id=request.workspace_id,
        workflow=WorkflowType.COMPARE,
        raw_input={"focus": request.focus},
        document_ids=request.document_ids,
        top_k=request.top_k,
    )
    return WorkflowResponse.from_run(run)


@api_router.post("/workflows/brief", response_model=WorkflowResponse)
async def brief(request: BriefRequest, container: ContainerDependency) -> WorkflowResponse:
    run = await container.workflows.execute(
        workspace_id=request.workspace_id,
        workflow=WorkflowType.BRIEF,
        raw_input={
            "objective": request.objective,
            "audience": request.audience,
            "max_points": request.max_points,
        },
        document_ids=request.document_ids,
        top_k=request.top_k,
    )
    return WorkflowResponse.from_run(run)


@api_router.get("/runs", response_model=RunListResponse)
async def list_runs(
    container: ContainerDependency,
    workspace_id: Annotated[str, Query(min_length=1, max_length=128)] = "default",
    workflow: Annotated[WorkflowType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RunListResponse:
    runs = await container.repository.list_runs(
        workspace_id=workspace_id,
        workflow=workflow,
        limit=limit,
    )
    return RunListResponse(items=[WorkflowResponse.from_run(run) for run in runs])


@api_router.get("/runs/{run_id}", response_model=WorkflowResponse)
async def get_run(
    run_id: UUID,
    container: ContainerDependency,
    workspace_id: Annotated[str, Query(min_length=1, max_length=128)] = "default",
) -> WorkflowResponse:
    run = await container.repository.get_run(run_id)
    if run.workspace_id != workspace_id:
        raise NotFoundError("workflow run not found", details={"run_id": str(run_id)})
    return WorkflowResponse.from_run(run)


@operations_router.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@operations_router.get("/readyz")
async def readiness(container: ContainerDependency) -> Response:
    repository_ready = await container.repository.ping()
    storage_ready = await container.object_store.ping()
    cache_ready = await container.cache.ping()
    required_ready = (
        repository_ready
        and storage_ready
        and (cache_ready or not container.settings.ready_requires_cache)
    )
    payload: dict[str, Any] = {
        "status": "ready" if required_ready else "not_ready",
        "dependencies": {
            "repository": repository_ready,
            "object_storage": storage_ready,
            "cache": cache_ready,
        },
    }
    return JSONResponse(payload, status_code=200 if required_ready else 503)


@operations_router.get("/metrics")
async def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
