from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

LAMBDA_DIR = Path(__file__).resolve().parents[2] / "infra" / "aws" / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
from s3_event_handler import normalize_record  # noqa: E402

from agentflow.worker import SQSIngestionBridge  # noqa: E402


async def test_lambda_payload_is_accepted_by_sqs_ingestion_bridge() -> None:
    payload = normalize_record(
        {
            "eventSource": "aws:s3",
            "eventName": "ObjectCreated:Put",
            "eventTime": "2026-08-09T12:00:00.000Z",
            "awsRegion": "us-west-2",
            "s3": {
                "bucket": {"name": "agentflow-documents"},
                "object": {
                    "key": "incoming%2Fworkspace-1%2Fpolicy+one.pdf",
                    "size": 2048,
                    "eTag": '"abc123"',
                    "versionId": "version-1",
                    "sequencer": "0055AED6DCD90281E5",
                },
            },
        },
        expected_bucket="agentflow-documents",
        ingest_prefix="incoming/",
        allowed_extensions=frozenset({".pdf"}),
        max_object_bytes=4096,
    )
    ingestion = SimpleNamespace(register_existing_object=AsyncMock())
    client = SimpleNamespace(delete_message=Mock())
    bridge = object.__new__(SQSIngestionBridge)
    bridge._queue_url = "https://sqs.us-west-2.amazonaws.com/123/jobs"
    bridge._expected_bucket = "agentflow-documents"
    bridge._ingestion = ingestion
    bridge._client = client

    await bridge._handle_message(
        {
            "Body": json.dumps(payload),
            "ReceiptHandle": "receipt-1",
        }
    )

    ingestion.register_existing_object.assert_awaited_once_with(
        workspace_id="workspace-1",
        object_key="incoming/workspace-1/policy one.pdf",
        idempotency_key=payload["idempotency_key"],
        expected_size_bytes=2048,
        object_version_id="version-1",
    )
    client.delete_message.assert_called_once_with(
        QueueUrl="https://sqs.us-west-2.amazonaws.com/123/jobs",
        ReceiptHandle="receipt-1",
    )


async def test_sqs_receive_requests_exactly_one_message() -> None:
    client = SimpleNamespace(receive_message=Mock(return_value={"Messages": []}))
    bridge = object.__new__(SQSIngestionBridge)
    bridge._queue_url = "https://sqs.us-west-2.amazonaws.com/123/jobs"
    bridge._wait_time = 20
    bridge._max_messages = 1
    bridge._client = client

    assert await bridge.receive_once() == 0
    client.receive_message.assert_called_once_with(
        QueueUrl=bridge._queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        MessageAttributeNames=["All"],
    )


def test_sqs_bridge_rejects_multi_message_configuration() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        SQSIngestionBridge(
            queue_url="https://sqs.us-west-2.amazonaws.com/123/jobs",
            ingestion=SimpleNamespace(),
            expected_bucket="agentflow-documents",
            region="us-west-2",
            endpoint_url=None,
            access_key_id=None,
            secret_access_key=None,
            wait_time_seconds=20,
            max_messages=2,
        )
