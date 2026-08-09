"""Evidence tools with explicit allowlists and invocation bounds."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from agentflow.errors import ValidationError
from agentflow.retrieval.hybrid import HybridRetriever


class RetrieveEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=200)
    corpus_revision: int = Field(ge=0)
    query: str = Field(min_length=1, max_length=20_000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=8, ge=1, le=50)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any]


def create_retrieve_evidence_tool(retriever: HybridRetriever) -> StructuredTool:
    async def retrieve_evidence(
        workspace_id: str,
        corpus_revision: int,
        query: str,
        document_ids: list[UUID],
        top_k: int,
    ) -> str:
        """Retrieve ranked document chunks for one fixed corpus revision."""

        result = await retriever.search(
            workspace_id=workspace_id,
            corpus_revision=corpus_revision,
            query=query,
            document_ids=document_ids,
            top_k=top_k,
        )
        return result.model_dump_json()

    return StructuredTool.from_function(
        coroutine=retrieve_evidence,
        name="retrieve_evidence",
        description=(
            "Retrieve bounded, ranked evidence chunks from the selected workspace and documents. "
            "The caller must provide the exact corpus revision."
        ),
        args_schema=RetrieveEvidenceInput,
    )


class BoundedToolRegistry:
    """Reject unknown tools and tool-call sequences beyond a declared bound."""

    def __init__(self, tools: list[BaseTool], *, max_calls: int) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be positive")
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("tool names must be unique")
        self._max_calls = max_calls

    @property
    def allowed_names(self) -> frozenset[str]:
        return frozenset(self._tools)

    async def invoke(self, call: ToolCall) -> Any:
        tool = self._tools.get(call.name)
        if tool is None:
            raise ValidationError(
                "workflow requested an unknown tool",
                details={"tool": call.name, "allowed": sorted(self.allowed_names)},
            )
        return await tool.ainvoke(call.arguments)

    async def invoke_many(self, calls: list[ToolCall]) -> list[Any]:
        if len(calls) > self._max_calls:
            raise ValidationError(
                "workflow exceeded its tool-call bound",
                details={"requested": len(calls), "maximum": self._max_calls},
            )
        results: list[Any] = []
        for call in calls:
            results.append(await self.invoke(call))
        return results
