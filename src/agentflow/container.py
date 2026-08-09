"""Explicit dependency construction for API and worker processes."""

from __future__ import annotations

from dataclasses import dataclass

from agentflow.cache import InMemoryJsonCache, RedisJsonCache
from agentflow.cache.base import JsonCache
from agentflow.config import Settings
from agentflow.extraction import DocumentExtractor, TextChunker
from agentflow.object_store import LocalObjectStore, S3ObjectStore
from agentflow.object_store.base import ObjectStore
from agentflow.providers import (
    DeterministicEmbeddingProvider,
    DeterministicResponseProvider,
    OpenAIEmbeddingProvider,
    OpenAIResponseProvider,
)
from agentflow.providers.base import EmbeddingProvider, ResponseProvider
from agentflow.repositories import InMemoryRepository, PostgresRepository
from agentflow.repositories.base import Repository
from agentflow.retrieval import HybridRetriever
from agentflow.services import IngestionService, WorkflowService
from agentflow.worker import IngestionWorker, SQSIngestionBridge
from agentflow.workflows import BoundedWorkflowEngine


def _secret(value: object | None) -> str | None:
    if value is None:
        return None
    get_secret_value = getattr(value, "get_secret_value", None)
    return str(get_secret_value() if get_secret_value else value)


@dataclass(slots=True)
class Container:
    settings: Settings
    repository: Repository
    cache: JsonCache
    object_store: ObjectStore
    embedding_provider: EmbeddingProvider
    response_provider: ResponseProvider
    ingestion: IngestionService
    workflows: WorkflowService
    worker: IngestionWorker

    async def close(self) -> None:
        await self.worker.close()
        await self.cache.close()
        await self.object_store.close()
        await self.repository.close()


async def build_container(settings: Settings) -> Container:
    if settings.use_postgres:
        repository: Repository = PostgresRepository(
            dsn=_secret(settings.database_url) or "",
            min_size=settings.database_pool_min_size,
            max_size=settings.database_pool_max_size,
            command_timeout_seconds=settings.database_command_timeout_seconds,
        )
    else:
        repository = InMemoryRepository()
    await repository.start()

    if settings.use_redis:
        cache: JsonCache = RedisJsonCache(_secret(settings.redis_url) or "")
    else:
        cache = InMemoryJsonCache()

    if settings.storage_backend == "s3":
        object_store: ObjectStore = S3ObjectStore(
            bucket=settings.s3_bucket or "",
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=_secret(settings.s3_access_key_id),
            secret_access_key=_secret(settings.s3_secret_access_key),
            force_path_style=settings.s3_force_path_style,
        )
    else:
        object_store = LocalObjectStore(settings.local_storage_path)

    if settings.embedding_provider == "openai":
        embedding_provider: EmbeddingProvider = OpenAIEmbeddingProvider(
            api_key=_secret(settings.openai_api_key) or "",
            model=settings.openai_embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=settings.provider_timeout_seconds,
            max_retries=settings.provider_max_retries,
        )
    else:
        embedding_provider = DeterministicEmbeddingProvider(settings.embedding_dimensions)

    if settings.response_provider == "openai":
        response_provider: ResponseProvider = OpenAIResponseProvider(
            api_key=_secret(settings.openai_api_key) or "",
            model=settings.openai_model or "",
            timeout_seconds=settings.provider_timeout_seconds,
            max_retries=settings.provider_max_retries,
        )
    else:
        response_provider = DeterministicResponseProvider()

    extractor = DocumentExtractor(
        allowed_extensions=settings.allowed_extensions,
        max_upload_bytes=settings.max_upload_bytes,
        max_extracted_chars=settings.max_extracted_chars,
        max_pdf_pages=settings.max_pdf_pages,
        max_docx_entries=settings.max_docx_entries,
        max_docx_uncompressed_bytes=settings.max_docx_uncompressed_bytes,
    )
    chunker = TextChunker(
        chunk_size_tokens=settings.chunk_size_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    ingestion = IngestionService(
        repository=repository,
        object_store=object_store,
        extractor=extractor,
        chunker=chunker,
        embedding_provider=embedding_provider,
        embedding_batch_size=settings.embedding_batch_size,
        worker_lease_seconds=settings.worker_lease_seconds,
        max_attempts=settings.worker_max_attempts,
    )
    retriever = HybridRetriever(
        repository=repository,
        cache=cache,
        embedding_provider=embedding_provider,
        retriever_version=settings.retriever_version,
        candidate_pool=settings.retrieval_candidate_pool,
        dense_weight=settings.dense_weight,
        sparse_weight=settings.sparse_weight,
        cache_ttl_seconds=settings.retrieval_cache_ttl_seconds,
    )
    engine = BoundedWorkflowEngine(
        repository=repository,
        response_cache=cache,
        retriever=retriever,
        response_provider=response_provider,
        prompt_version=settings.prompt_version,
        graph_version=settings.graph_version,
        response_cache_ttl_seconds=settings.cache_ttl_seconds,
    )
    workflows = WorkflowService(repository=repository, engine=engine)

    sqs_bridge = None
    if settings.sqs_queue_url is not None:
        if settings.storage_backend != "s3" or not settings.s3_bucket:
            raise ValueError("SQS ingestion requires S3 object storage")
        sqs_bridge = SQSIngestionBridge(
            queue_url=_secret(settings.sqs_queue_url) or "",
            ingestion=ingestion,
            expected_bucket=settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.sqs_endpoint_url or settings.s3_endpoint_url,
            access_key_id=_secret(settings.s3_access_key_id),
            secret_access_key=_secret(settings.s3_secret_access_key),
            wait_time_seconds=settings.sqs_wait_time_seconds,
            max_messages=settings.sqs_max_messages,
        )
    worker = IngestionWorker(
        repository=repository,
        ingestion=ingestion,
        poll_seconds=settings.worker_poll_seconds,
        lease_seconds=settings.worker_lease_seconds,
        worker_id=settings.worker_id,
        sqs_bridge=sqs_bridge,
    )
    return Container(
        settings=settings,
        repository=repository,
        cache=cache,
        object_store=object_store,
        embedding_provider=embedding_provider,
        response_provider=response_provider,
        ingestion=ingestion,
        workflows=workflows,
        worker=worker,
    )
