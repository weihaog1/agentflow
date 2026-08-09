"""Visible LangGraph execution for the three supported workflows."""

from __future__ import annotations

import math
import time
from contextlib import suppress
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

import structlog
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError as PydanticValidationError

from agentflow.cache.base import JsonCache
from agentflow.cache.keys import response_cache_key
from agentflow.domain import (
    Citation,
    ProviderResponse,
    RetrievedChunk,
    RunStep,
    WorkflowExecution,
    WorkflowType,
)
from agentflow.errors import DependencyUnavailableError, ValidationError
from agentflow.evidence_text import select_evidence_excerpt
from agentflow.providers.base import ResponseProvider
from agentflow.repositories.base import Repository
from agentflow.retrieval.hybrid import HybridRetriever, RetrievalResult
from agentflow.tools.evidence import BoundedToolRegistry, ToolCall, create_retrieve_evidence_tool
from agentflow.workflows.normalization import normalize_workflow_input

logger = structlog.get_logger(__name__)


class WorkflowState(TypedDict, total=False):
    workspace_id: str
    corpus_revision: int
    workflow: str
    raw_input: dict[str, Any]
    normalized_input: dict[str, Any]
    document_ids: list[str]
    top_k: int
    query: str
    cache_key: str
    cache_hit: bool
    evidence: list[dict[str, Any]]
    provider_response: dict[str, Any]
    result: dict[str, Any]
    citations: list[dict[str, Any]]
    verified: bool
    evidence_gap: str | None
    steps: list[dict[str, Any]]
    metrics: dict[str, Any]


class BoundedWorkflowEngine:
    """One bounded graph parameterized by the supported workflow type."""

    def __init__(
        self,
        *,
        repository: Repository,
        response_cache: JsonCache,
        retriever: HybridRetriever,
        response_provider: ResponseProvider,
        prompt_version: str,
        graph_version: str,
        response_cache_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._cache = response_cache
        self._provider = response_provider
        self._prompt_version = prompt_version
        self._graph_version = graph_version
        self._cache_ttl = response_cache_ttl_seconds
        self._retriever_identity = retriever.identity.model_dump(mode="json")
        retrieval_tool = create_retrieve_evidence_tool(retriever)
        self._tools = BoundedToolRegistry([retrieval_tool], max_calls=20)
        self._graph = self._build_graph()

    @property
    def model_id(self) -> str:
        return self._provider.identifier

    @property
    def allowed_tools(self) -> frozenset[str]:
        return self._tools.allowed_names

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    @property
    def graph_version(self) -> str:
        return self._graph_version

    async def run(
        self,
        *,
        workspace_id: str,
        corpus_revision: int,
        workflow: WorkflowType,
        raw_input: dict[str, Any],
        document_ids: list[UUID],
        top_k: int,
    ) -> WorkflowExecution:
        initial: WorkflowState = {
            "workspace_id": workspace_id,
            "corpus_revision": corpus_revision,
            "workflow": workflow.value,
            "raw_input": raw_input,
            "document_ids": [str(value) for value in document_ids],
            "top_k": top_k,
            "steps": [],
            "metrics": {"generation_calls": 0, "retrieval_cache_hit": False},
            "cache_hit": False,
            "verified": False,
        }
        final = cast(
            WorkflowState,
            await self._graph.ainvoke(initial, config={"recursion_limit": 12}),
        )
        try:
            citations = [Citation.model_validate(value) for value in final.get("citations", [])]
            return WorkflowExecution(
                result=final.get("result", {}),
                citations=citations,
                cached=final.get("cache_hit", False),
                verified=final.get("verified", False),
                evidence_gap=final.get("evidence_gap"),
                steps=[RunStep.model_validate(value) for value in final.get("steps", [])],
                metrics=final.get("metrics", {}),
            )
        except PydanticValidationError as exc:
            raise ValidationError("workflow produced invalid state") from exc

    def _build_graph(self) -> Any:
        graph = StateGraph(WorkflowState)
        graph.add_node("normalize", self._normalize)
        graph.add_node("cache_lookup", self._cache_lookup)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("reason", self._reason)
        graph.add_node("verify", self._verify)
        graph.add_node("cache_write", self._cache_write)
        graph.add_node("safe_fail", self._safe_fail)
        graph.add_edge(START, "normalize")
        graph.add_edge("normalize", "cache_lookup")
        graph.add_conditional_edges(
            "cache_lookup",
            self._route_cache,
            {"cached": END, "retrieve": "retrieve"},
        )
        graph.add_edge("retrieve", "reason")
        graph.add_edge("reason", "verify")
        graph.add_conditional_edges(
            "verify",
            self._route_verification,
            {"valid": "cache_write", "invalid": "safe_fail"},
        )
        graph.add_edge("cache_write", END)
        graph.add_edge("safe_fail", END)
        return graph.compile()

    async def _normalize(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        workflow = WorkflowType(state["workflow"])
        normalized, query = normalize_workflow_input(workflow, state["raw_input"])
        step = self._step("normalize", started, input_fields=sorted(normalized))
        return {"normalized_input": normalized, "query": query, "steps": [*state["steps"], step]}

    async def _cache_lookup(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        workflow = WorkflowType(state["workflow"])
        key = response_cache_key(
            workspace_id=state["workspace_id"],
            corpus_revision=state["corpus_revision"],
            workflow=workflow,
            normalized_input=state["normalized_input"],
            document_ids=state["document_ids"],
            prompt_version=self._prompt_version,
            graph_version=self._graph_version,
            model_id=self._provider.identifier,
            top_k=state["top_k"],
            retriever_identity=self._retriever_identity,
        )
        cached: dict[str, Any] | None = None
        try:
            cached = await self._cache.get_json(key)
        except DependencyUnavailableError:
            logger.warning("response_cache_unavailable", operation="get")
        if cached is not None:
            try:
                execution = WorkflowExecution.model_validate(cached)
                if execution.verified and execution.citations:
                    step = self._step("cache_lookup", started, hit=True)
                    metrics = {**state["metrics"], "response_cache_hit": True}
                    return {
                        "cache_key": key,
                        "cache_hit": True,
                        "result": execution.result,
                        "citations": [item.model_dump(mode="json") for item in execution.citations],
                        "verified": True,
                        "evidence_gap": None,
                        "steps": [*state["steps"], step],
                        "metrics": metrics,
                    }
            except PydanticValidationError:
                with suppress(DependencyUnavailableError):
                    await self._cache.delete(key)
        step = self._step("cache_lookup", started, hit=False)
        return {
            "cache_key": key,
            "cache_hit": False,
            "steps": [*state["steps"], step],
            "metrics": {**state["metrics"], "response_cache_hit": False},
        }

    async def _retrieve(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        base_arguments = {
            "workspace_id": state["workspace_id"],
            "corpus_revision": state["corpus_revision"],
            "query": state["query"],
        }
        if state["workflow"] == WorkflowType.COMPARE.value and state["document_ids"]:
            per_document = max(1, math.ceil(state["top_k"] / len(state["document_ids"])))
            calls = [
                ToolCall(
                    name="retrieve_evidence",
                    arguments={
                        **base_arguments,
                        "document_ids": [document_id],
                        "top_k": per_document,
                    },
                )
                for document_id in state["document_ids"]
            ]
            raw_results = await self._tools.invoke_many(calls)
            retrievals = [RetrievalResult.model_validate_json(str(value)) for value in raw_results]
            items: list[RetrievedChunk] = []
            for rank in range(per_document):
                for retrieval_result in retrievals:
                    if rank < len(retrieval_result.items):
                        items.append(retrieval_result.items[rank])
            retrieval = RetrievalResult(
                items=items[: max(state["top_k"], len(state["document_ids"]))],
                cached=bool(retrievals) and all(value.cached for value in retrievals),
                corpus_revision=state["corpus_revision"],
            )
            tool_call_count = len(calls)
        else:
            call = ToolCall(
                name="retrieve_evidence",
                arguments={
                    **base_arguments,
                    "document_ids": state["document_ids"],
                    "top_k": state["top_k"],
                },
            )
            raw_result = await self._tools.invoke(call)
            retrieval = RetrievalResult.model_validate_json(str(raw_result))
            tool_call_count = 1
        step = self._step(
            "retrieve",
            started,
            evidence_count=len(retrieval.items),
            cache_hit=retrieval.cached,
            tool="retrieve_evidence",
            tool_call_count=tool_call_count,
        )
        return {
            "evidence": [item.model_dump(mode="json") for item in retrieval.items],
            "steps": [*state["steps"], step],
            "metrics": {
                **state["metrics"],
                "retrieval_cache_hit": retrieval.cached,
                "evidence_count": len(retrieval.items),
            },
        }

    async def _reason(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        evidence = [RetrievedChunk.model_validate(item) for item in state.get("evidence", [])]
        if not evidence:
            step = self._step("reason", started, status="skipped", reason="no_evidence")
            return {
                "evidence_gap": "No indexed evidence matched this request.",
                "steps": [*state["steps"], step],
            }
        response = await self._provider.generate(
            workflow=WorkflowType(state["workflow"]),
            normalized_input=state["normalized_input"],
            evidence=evidence,
        )
        citations = self._citations(
            response,
            evidence,
            workflow=WorkflowType(state["workflow"]),
            normalized_input=state["normalized_input"],
        )
        result = {**response.structured, "text": response.text}
        step = self._step(
            "reason",
            started,
            model=response.model_id,
            citation_count=len(citations),
        )
        metrics = {
            **state["metrics"],
            "generation_calls": response.usage.generation_calls,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }
        return {
            "provider_response": response.model_dump(mode="json"),
            "result": result,
            "citations": [citation.model_dump(mode="json") for citation in citations],
            "steps": [*state["steps"], step],
            "metrics": metrics,
        }

    async def _verify(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        citations = [Citation.model_validate(value) for value in state.get("citations", [])]
        current_revision = await self._repository.get_corpus_revision(state["workspace_id"])
        valid = bool(citations) and current_revision == state["corpus_revision"]
        reason: str | None = state.get("evidence_gap")
        if citations:
            chunks = await self._repository.get_chunks(
                [citation.chunk_id for citation in citations]
            )
            chunk_text = {chunk.id: chunk.text for chunk in chunks}
            valid = valid and len(chunks) == len(citations)
            valid = valid and all(
                citation.quote and citation.quote in chunk_text.get(citation.chunk_id, "")
                for citation in citations
            )
        if state["workflow"] == WorkflowType.COMPARE.value:
            cited_documents = {str(citation.document_id) for citation in citations}
            selected_documents = set(state["document_ids"])
            valid = valid and selected_documents.issubset(cited_documents)
        if not valid and reason is None:
            reason = (
                "The corpus changed during this run. Please retry."
                if current_revision != state["corpus_revision"]
                else "The generated response did not pass citation verification."
            )
        step = self._step("verify", started, valid=valid, citation_count=len(citations))
        return {
            "verified": valid,
            "evidence_gap": reason,
            "steps": [*state["steps"], step],
            "metrics": {**state["metrics"], "citation_count": len(citations), "verified": valid},
        }

    async def _cache_write(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        cached = WorkflowExecution(
            result=state["result"],
            citations=[Citation.model_validate(value) for value in state["citations"]],
            cached=False,
            verified=True,
            steps=[],
            metrics=state["metrics"],
        )
        status = "completed"
        try:
            await self._cache.set_json(
                state["cache_key"],
                cached.model_dump(mode="json"),
                ttl_seconds=self._cache_ttl,
            )
        except DependencyUnavailableError:
            logger.warning("response_cache_unavailable", operation="set")
            status = "degraded"
        step = self._step("cache_write", started, status=status)
        return {"steps": [*state["steps"], step]}

    async def _safe_fail(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        message = state.get("evidence_gap") or (
            "The evidence was insufficient for a verified response."
        )
        step = self._step("safe_fail", started, evidence_gap=message)
        return {
            "result": {"text": message},
            "citations": [],
            "verified": False,
            "evidence_gap": message,
            "steps": [*state["steps"], step],
        }

    @staticmethod
    def _route_cache(state: WorkflowState) -> Literal["cached", "retrieve"]:
        return "cached" if state.get("cache_hit") else "retrieve"

    @staticmethod
    def _route_verification(state: WorkflowState) -> Literal["valid", "invalid"]:
        return "valid" if state.get("verified") else "invalid"

    @staticmethod
    def _citations(
        response: ProviderResponse,
        evidence: list[RetrievedChunk],
        *,
        workflow: WorkflowType,
        normalized_input: dict[str, Any],
    ) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[UUID] = set()
        if workflow == WorkflowType.QUESTION:
            query = str(normalized_input.get("question", ""))
        elif workflow == WorkflowType.COMPARE:
            query = str(normalized_input.get("focus", ""))
        else:
            query = " ".join(
                (
                    str(normalized_input.get("objective", "")),
                    str(normalized_input.get("audience", "")),
                )
            )
        for index in response.citation_indices:
            if index < 0 or index >= len(evidence):
                raise ValidationError("provider returned an out-of-range citation")
            item = evidence[index]
            if item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            quote = select_evidence_excerpt(item.text, query).text
            citations.append(
                Citation(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    document_version_id=item.document_version_id,
                    document_title=item.document_title,
                    chunk_ordinal=item.chunk_ordinal,
                    quote=quote,
                    locator=item.locator,
                    score=item.score,
                )
            )
        return citations

    @staticmethod
    def _step(
        name: str,
        started: float,
        *,
        status: str = "completed",
        **detail: Any,
    ) -> dict[str, Any]:
        return RunStep(
            name=name,
            status=status,
            latency_ms=(time.perf_counter() - started) * 1000,
            detail=detail,
        ).model_dump(mode="json")
