"""Durable workflow run orchestration."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

import structlog

from agentflow.domain import (
    DocumentStatus,
    RunStatus,
    WorkflowRun,
    WorkflowType,
    utc_now,
)
from agentflow.errors import ValidationError
from agentflow.metrics import WORKFLOW_DURATION, WORKFLOW_RUNS
from agentflow.repositories.base import Repository
from agentflow.workflows.graph import BoundedWorkflowEngine
from agentflow.workflows.normalization import normalize_workflow_input

logger = structlog.get_logger(__name__)


class WorkflowService:
    def __init__(self, *, repository: Repository, engine: BoundedWorkflowEngine) -> None:
        self._repository = repository
        self._engine = engine

    async def execute(
        self,
        *,
        workspace_id: str,
        workflow: WorkflowType,
        raw_input: dict[str, Any],
        document_ids: list[UUID],
        top_k: int,
    ) -> WorkflowRun:
        started = time.perf_counter()
        if workflow == WorkflowType.COMPARE and len(set(document_ids)) < 2:
            raise ValidationError("comparison requires at least two distinct documents")
        document_ids = list(dict.fromkeys(document_ids))
        await self._validate_documents(workspace_id, document_ids)
        normalized_input, _ = normalize_workflow_input(workflow, raw_input)
        corpus_revision = await self._repository.get_corpus_revision(workspace_id)
        run = WorkflowRun(
            workspace_id=workspace_id,
            workflow=workflow,
            corpus_revision=corpus_revision,
            normalized_input=normalized_input,
            document_ids=document_ids,
            model_id=self._engine.model_id,
            prompt_version=self._engine.prompt_version,
            graph_version=self._engine.graph_version,
        )
        await self._repository.create_run(run)
        try:
            execution = await self._engine.run(
                workspace_id=workspace_id,
                corpus_revision=corpus_revision,
                workflow=workflow,
                raw_input=raw_input,
                document_ids=document_ids,
                top_k=top_k,
            )
            run.cached = execution.cached
            run.result = execution.result
            run.citations = [
                citation.model_copy(update={"citation_id": uuid4()})
                for citation in execution.citations
            ]
            run.evidence_gap = execution.evidence_gap
            run.steps = execution.steps
            retrieval_latency = sum(
                step.latency_ms for step in execution.steps if step.name == "retrieve"
            )
            reasoning_latency = sum(
                step.latency_ms for step in execution.steps if step.name == "reason"
            )
            run.metrics = {
                **execution.metrics,
                "total_latency_ms": (time.perf_counter() - started) * 1000,
                "retrieval_latency_ms": retrieval_latency,
                "reasoning_latency_ms": reasoning_latency,
            }
            run.status = RunStatus.COMPLETED if execution.verified else RunStatus.EVIDENCE_GAP
            run.completed_at = utc_now()
            await self._repository.save_run(run)
            outcome = run.status.value
            WORKFLOW_RUNS.labels(
                workflow=workflow.value,
                outcome=outcome,
                cached=str(run.cached).lower(),
            ).inc()
            WORKFLOW_DURATION.labels(workflow=workflow.value).observe(time.perf_counter() - started)
            logger.info(
                "workflow_run_completed",
                run_id=str(run.id),
                workflow=workflow.value,
                status=run.status.value,
                cached=run.cached,
                citation_count=len(run.citations),
            )
            return run
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error_code = getattr(exc, "code", "workflow_internal_error")
            run.error_message = str(exc)[:2000]
            run.completed_at = utc_now()
            run.metrics = {"total_latency_ms": (time.perf_counter() - started) * 1000}
            await self._repository.save_run(run)
            WORKFLOW_RUNS.labels(
                workflow=workflow.value,
                outcome="failed",
                cached="false",
            ).inc()
            logger.exception(
                "workflow_run_failed",
                run_id=str(run.id),
                workflow=workflow.value,
                error_code=run.error_code,
            )
            raise

    async def _validate_documents(self, workspace_id: str, document_ids: list[UUID]) -> None:
        for document_id in document_ids:
            document = await self._repository.get_document(document_id)
            if document.workspace_id != workspace_id:
                raise ValidationError("selected document belongs to another workspace")
            if document.status != DocumentStatus.READY:
                raise ValidationError(
                    "selected document is not ready",
                    details={"document_id": str(document_id), "status": document.status.value},
                )
