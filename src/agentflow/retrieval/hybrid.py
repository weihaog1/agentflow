"""Revision-aware hybrid retrieval with disposable caching."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from agentflow.cache.base import JsonCache
from agentflow.cache.keys import normalize_text, retrieval_cache_key
from agentflow.domain import RetrievedChunk
from agentflow.errors import DependencyUnavailableError, ValidationError
from agentflow.providers.base import EmbeddingProvider
from agentflow.repositories.base import Repository

logger = structlog.get_logger(__name__)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RetrievedChunk]
    cached: bool = False
    corpus_revision: int = Field(ge=0)


class RetrieverIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retriever_version: str
    embedding_provider_id: str
    candidate_pool: int = Field(ge=1)
    dense_weight: float = Field(ge=0, le=1)
    sparse_weight: float = Field(ge=0, le=1)


class HybridRetriever:
    def __init__(
        self,
        *,
        repository: Repository,
        cache: JsonCache,
        embedding_provider: EmbeddingProvider,
        retriever_version: str,
        candidate_pool: int,
        dense_weight: float,
        sparse_weight: float,
        cache_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._embedding_provider = embedding_provider
        self._retriever_version = retriever_version
        self._candidate_pool = candidate_pool
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight
        self._cache_ttl = cache_ttl_seconds
        self._identity = RetrieverIdentity(
            retriever_version=retriever_version,
            embedding_provider_id=embedding_provider.identifier,
            candidate_pool=candidate_pool,
            dense_weight=dense_weight,
            sparse_weight=sparse_weight,
        )

    @property
    def identity(self) -> RetrieverIdentity:
        return self._identity

    async def search(
        self,
        *,
        workspace_id: str,
        corpus_revision: int,
        query: str,
        document_ids: list[UUID],
        top_k: int,
    ) -> RetrievalResult:
        normalized_query = normalize_text(query)
        if not normalized_query:
            raise ValidationError("retrieval query cannot be empty")
        key = retrieval_cache_key(
            workspace_id=workspace_id,
            corpus_revision=corpus_revision,
            normalized_query=normalized_query,
            retriever_identity=self._identity.model_dump(mode="json"),
            document_ids=[str(value) for value in document_ids],
            top_k=top_k,
        )
        cached = await self._cache_get(key)
        if cached is not None:
            try:
                result = RetrievalResult.model_validate(cached)
                result.cached = True
                return result
            except PydanticValidationError:
                await self._cache_delete(key)

        query_embedding = await self._embedding_provider.embed(normalized_query)
        items = await self._repository.hybrid_search(
            workspace_id=workspace_id,
            query=normalized_query,
            query_embedding=query_embedding,
            document_ids=document_ids,
            top_k=top_k,
            candidate_pool=self._candidate_pool,
            dense_weight=self._dense_weight,
            sparse_weight=self._sparse_weight,
        )
        result = RetrievalResult(items=items, corpus_revision=corpus_revision)
        await self._cache_set(key, result.model_dump(mode="json"))
        return result

    async def _cache_get(self, key: str) -> dict[str, Any] | None:
        try:
            return await self._cache.get_json(key)
        except DependencyUnavailableError:
            logger.warning("retrieval_cache_unavailable", operation="get")
            return None

    async def _cache_set(self, key: str, value: dict[str, Any]) -> None:
        try:
            await self._cache.set_json(key, value, ttl_seconds=self._cache_ttl)
        except DependencyUnavailableError:
            logger.warning("retrieval_cache_unavailable", operation="set")

    async def _cache_delete(self, key: str) -> None:
        try:
            await self._cache.delete(key)
        except DependencyUnavailableError:
            logger.warning("retrieval_cache_unavailable", operation="delete")
