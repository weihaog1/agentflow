from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentflow.config import Settings


def test_local_defaults_need_no_cloud_or_model_credentials(tmp_path) -> None:
    settings = Settings(_env_file=None, local_storage_path=tmp_path)

    assert settings.environment == "local"
    assert settings.embedding_provider == "local"
    assert settings.response_provider == "local"
    assert settings.storage_backend == "local"
    assert settings.use_postgres is False
    assert settings.use_redis is False


def test_production_rejects_memory_repository_and_local_storage() -> None:
    with pytest.raises(ValidationError, match="production requires PostgreSQL"):
        Settings(
            _env_file=None,
            environment="production",
            repository_backend="memory",
        )


def test_extensions_are_normalized_from_environment_shape() -> None:
    settings = Settings(_env_file=None, allowed_extensions="PDF, .Md, pdf")

    assert settings.allowed_extensions == (".md", ".pdf")


def test_openai_response_provider_requires_key_and_model() -> None:
    with pytest.raises(ValidationError, match="openai_api_key"):
        Settings(_env_file=None, response_provider="openai", openai_model="gpt-test")


def test_sqs_consumer_rejects_multi_message_receives() -> None:
    with pytest.raises(ValidationError, match="Input should be 1"):
        Settings(_env_file=None, sqs_max_messages=2)
