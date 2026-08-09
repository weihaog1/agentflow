"""Provider protocols that keep workflow code vendor-neutral."""

from __future__ import annotations

from typing import Protocol

from agentflow.domain import ProviderResponse, RetrievedChunk, WorkflowType


class EmbeddingProvider(Protocol):
    @property
    def identifier(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: list[str]) -> list[list[float]]: ...


class ResponseProvider(Protocol):
    @property
    def identifier(self) -> str: ...

    async def generate(
        self,
        *,
        workflow: WorkflowType,
        normalized_input: dict[str, object],
        evidence: list[RetrievedChunk],
    ) -> ProviderResponse: ...
