"""Environment-backed configuration with production safety validation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AgentFlow runtime settings.

    The default profile is a no-key local demo. Production requires PostgreSQL
    and rejects the in-memory system-of-record adapter.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    json_logs: bool = True
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    repository_backend: Literal["auto", "memory", "postgres"] = "auto"
    database_url: SecretStr | None = None
    database_pool_min_size: int = Field(default=1, ge=1, le=100)
    database_pool_max_size: int = Field(default=10, ge=1, le=100)
    database_command_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    cache_backend: Literal["auto", "memory", "redis"] = "auto"
    redis_url: SecretStr | None = None
    cache_ttl_seconds: int = Field(default=3600, ge=1, le=604800)
    retrieval_cache_ttl_seconds: int = Field(default=900, ge=1, le=86400)
    ready_requires_cache: bool = False

    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = Path(".data/objects")
    s3_bucket: str | None = None
    s3_region: str = "us-west-2"
    s3_endpoint_url: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = False
    sqs_queue_url: SecretStr | None = None
    sqs_endpoint_url: str | None = None
    sqs_wait_time_seconds: int = Field(default=20, ge=0, le=20)
    sqs_max_messages: Literal[1] = 1

    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_extracted_chars: int = Field(default=4_000_000, ge=1000)
    max_pdf_pages: int = Field(default=500, ge=1, le=5000)
    max_docx_entries: int = Field(default=5000, ge=10)
    max_docx_uncompressed_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    allowed_extensions: tuple[str, ...] = (".txt", ".md", ".pdf", ".docx")

    chunk_size_tokens: int = Field(default=700, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=100, ge=0, le=1000)
    embedding_dimensions: int = Field(default=384, ge=32, le=4096)
    embedding_batch_size: int = Field(default=64, ge=1, le=2048)

    embedding_provider: Literal["local", "openai"] = "local"
    response_provider: Literal["local", "openai"] = "local"
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    provider_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    provider_max_retries: int = Field(default=2, ge=0, le=8)

    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    retrieval_candidate_pool: int = Field(default=50, ge=5, le=500)
    dense_weight: float = Field(default=0.55, ge=0, le=1)
    sparse_weight: float = Field(default=0.45, ge=0, le=1)
    retriever_version: str = "hybrid-v1"
    prompt_version: str = "evidence-v1"
    graph_version: str = "bounded-v1"

    worker_id: str | None = None
    worker_poll_seconds: float = Field(default=1.0, ge=0.05, le=60)
    worker_lease_seconds: int = Field(default=120, ge=10, le=3600)
    worker_max_attempts: int = Field(default=4, ge=1, le=20)
    embedded_worker: bool = True
    shutdown_grace_seconds: float = Field(default=15.0, ge=0, le=120)

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _parse_extensions(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("allowed_extensions")
    @classmethod
    def _normalize_extensions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            sorted({item.lower() if item.startswith(".") else f".{item.lower()}" for item in value})
        )
        if not normalized:
            raise ValueError("at least one document extension must be allowed")
        return normalized

    @model_validator(mode="after")
    def _validate_adapters(self) -> Settings:
        if self.database_pool_min_size > self.database_pool_max_size:
            raise ValueError("database_pool_min_size cannot exceed database_pool_max_size")
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        if abs((self.dense_weight + self.sparse_weight) - 1.0) > 0.0001:
            raise ValueError("dense_weight and sparse_weight must sum to 1")
        if self.repository_backend == "postgres" and self.database_url is None:
            raise ValueError("database_url is required for the postgres repository")
        if self.use_postgres and self.embedding_dimensions != 384:
            raise ValueError("PostgreSQL v0.1 requires 384-dimensional embeddings")
        if self.cache_backend == "redis" and self.redis_url is None:
            raise ValueError("redis_url is required for the Redis cache")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("s3_bucket is required for S3 storage")
        uses_openai = self.embedding_provider == "openai" or self.response_provider == "openai"
        if uses_openai and self.openai_api_key is None:
            raise ValueError("openai_api_key is required for OpenAI providers")
        if self.response_provider == "openai" and not self.openai_model:
            raise ValueError("openai_model is required for the OpenAI response provider")
        if self.environment == "production":
            if self.repository_backend == "memory" or self.database_url is None:
                raise ValueError("production requires PostgreSQL")
            if self.storage_backend == "local":
                raise ValueError("production requires S3 object storage")
        return self

    @property
    def use_postgres(self) -> bool:
        return self.repository_backend == "postgres" or (
            self.repository_backend == "auto" and self.database_url is not None
        )

    @property
    def use_redis(self) -> bool:
        return self.cache_backend == "redis" or (
            self.cache_backend == "auto" and self.redis_url is not None
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings singleton."""

    return Settings()
