"""Long-running ingestion worker and AWS SQS ingress bridge."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import uuid4

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from agentflow.errors import AgentFlowError, DependencyUnavailableError, ValidationError
from agentflow.metrics import WORKER_ACTIVE
from agentflow.repositories.base import Repository
from agentflow.services.ingestion import IngestionService

logger = structlog.get_logger(__name__)


class S3EventSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["s3"]
    region: str
    bucket: str
    key: str
    filename: str
    version_id: str = Field(min_length=1)
    etag: str
    size_bytes: int = Field(gt=0)
    sequencer: str
    event_name: str

    @field_validator("version_id")
    @classmethod
    def _validate_version_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("version_id must be nonempty")
        return normalized


class NormalizedS3IngestionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    job_type: Literal["document.ingest"]
    workspace_id: str
    idempotency_key: str = Field(min_length=64, max_length=64)
    occurred_at: str
    source: S3EventSource


class SQSIngestionBridge:
    """Translate validated SQS messages into durable repository jobs."""

    def __init__(
        self,
        *,
        queue_url: str,
        ingestion: IngestionService,
        expected_bucket: str,
        region: str,
        endpoint_url: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
        wait_time_seconds: int,
        max_messages: int,
    ) -> None:
        if max_messages != 1:
            raise ValueError("SQS ingestion requires exactly one message per receive")
        client_options: dict[str, Any] = {
            "service_name": "sqs",
            "region_name": region,
            "endpoint_url": endpoint_url,
            "config": Config(retries={"max_attempts": 4, "mode": "standard"}),
        }
        if access_key_id is not None:
            client_options["aws_access_key_id"] = access_key_id
        if secret_access_key is not None:
            client_options["aws_secret_access_key"] = secret_access_key
        self._client = boto3.client(**client_options)
        self._queue_url = queue_url
        self._ingestion = ingestion
        self._expected_bucket = expected_bucket
        self._wait_time = wait_time_seconds
        self._max_messages = max_messages

    async def receive_once(self) -> int:
        try:
            response = await asyncio.to_thread(
                self._client.receive_message,
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=self._max_messages,
                WaitTimeSeconds=self._wait_time,
                MessageAttributeNames=["All"],
            )
        except (BotoCoreError, ClientError) as exc:
            raise DependencyUnavailableError("SQS receive failed") from exc
        messages = response.get("Messages", [])
        accepted = 0
        for message in messages:
            try:
                await self._handle_message(message)
                accepted += 1
            except (
                AgentFlowError,
                PydanticValidationError,
                json.JSONDecodeError,
                TypeError,
            ) as exc:
                logger.warning(
                    "sqs_ingestion_message_rejected",
                    message_id=message.get("MessageId"),
                    error_type=type(exc).__name__,
                )
        return accepted

    async def _handle_message(self, message: dict[str, Any]) -> None:
        body = message.get("Body")
        receipt_handle = message.get("ReceiptHandle")
        if not isinstance(body, str) or not isinstance(receipt_handle, str):
            raise ValidationError("SQS message is missing body or receipt handle")
        event = NormalizedS3IngestionEvent.model_validate(json.loads(body))
        self._validate_event(event)
        await self._ingestion.register_existing_object(
            workspace_id=event.workspace_id,
            object_key=event.source.key,
            idempotency_key=event.idempotency_key,
            expected_size_bytes=event.source.size_bytes,
            object_version_id=event.source.version_id,
        )
        try:
            await asyncio.to_thread(
                self._client.delete_message,
                QueueUrl=self._queue_url,
                ReceiptHandle=receipt_handle,
            )
        except (BotoCoreError, ClientError) as exc:
            raise DependencyUnavailableError("SQS message acknowledgement failed") from exc
        logger.info(
            "sqs_ingestion_job_registered",
            workspace_id=event.workspace_id,
            object_key=event.source.key,
        )

    def _validate_event(self, event: NormalizedS3IngestionEvent) -> None:
        if event.source.bucket != self._expected_bucket:
            raise ValidationError("SQS event bucket does not match configured storage")
        path = PurePosixPath(event.source.key)
        if (
            path.is_absolute()
            or len(path.parts) != 3
            or path.parts[0] != "incoming"
            or path.parts[1] != event.workspace_id
            or path.parts[2] != event.source.filename
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValidationError("SQS event key does not match the incoming workspace contract")

    async def close(self) -> None:
        self._client.close()


class IngestionWorker:
    def __init__(
        self,
        *,
        repository: Repository,
        ingestion: IngestionService,
        poll_seconds: float,
        lease_seconds: int,
        worker_id: str | None = None,
        sqs_bridge: SQSIngestionBridge | None = None,
    ) -> None:
        default_id = f"{socket.gethostname()}-{os.getpid()}-{str(uuid4())[:8]}"
        self.worker_id = worker_id or default_id
        self._repository = repository
        self._ingestion = ingestion
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        self._sqs = sqs_bridge
        self._stop = asyncio.Event()

    async def run_once(self) -> bool:
        job = await self._repository.claim_next_job(
            worker_id=self.worker_id,
            lease_seconds=self._lease_seconds,
        )
        if job is None:
            return False
        await self._ingestion.process(job, worker_id=self.worker_id)
        return True

    async def run_forever(self) -> None:
        self._stop.clear()
        WORKER_ACTIVE.set(1)
        logger.info("ingestion_worker_started", worker_id=self.worker_id, sqs=bool(self._sqs))
        tasks = [asyncio.create_task(self._job_loop(), name="agentflow-job-loop")]
        if self._sqs is not None:
            tasks.append(asyncio.create_task(self._sqs_loop(), name="agentflow-sqs-loop"))
        try:
            await asyncio.gather(*tasks)
        finally:
            self._stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            WORKER_ACTIVE.set(0)
            logger.info("ingestion_worker_stopped", worker_id=self.worker_id)

    async def stop(self) -> None:
        self._stop.set()

    async def close(self) -> None:
        await self.stop()
        if self._sqs is not None:
            await self._sqs.close()

    async def _job_loop(self) -> None:
        while not self._stop.is_set():
            handled = await self.run_once()
            if not handled:
                await self._wait(self._poll_seconds)

    async def _sqs_loop(self) -> None:
        assert self._sqs is not None
        while not self._stop.is_set():
            try:
                accepted = await self._sqs.receive_once()
                if not accepted:
                    await self._wait(self._poll_seconds)
            except DependencyUnavailableError:
                logger.exception("sqs_ingestion_poll_failed")
                await self._wait(min(max(self._poll_seconds * 5, 1), 30))

    async def _wait(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return
