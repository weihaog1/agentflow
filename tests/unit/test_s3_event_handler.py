from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

LAMBDA_DIR = Path(__file__).resolve().parents[2] / "infra" / "aws" / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
from s3_event_handler import EventValidationError, lambda_handler, normalize_record  # noqa: E402


def s3_record(
    *,
    bucket: str = "agentflow-documents",
    key: str = "incoming%2Fworkspace-1%2Fpolicy+one.pdf",
    size: int = 1024,
) -> dict[str, object]:
    return {
        "eventSource": "aws:s3",
        "eventName": "ObjectCreated:Put",
        "eventTime": "2026-08-09T12:00:00.000Z",
        "awsRegion": "us-west-2",
        "s3": {
            "bucket": {"name": bucket},
            "object": {
                "key": key,
                "size": size,
                "eTag": '"abc123"',
                "versionId": "version-1",
                "sequencer": "0055AED6DCD90281E5",
            },
        },
    }


def test_normalize_record_decodes_key_and_builds_stable_identity() -> None:
    first = normalize_record(
        s3_record(),
        expected_bucket="agentflow-documents",
        ingest_prefix="incoming/",
        allowed_extensions=frozenset({".pdf"}),
        max_object_bytes=2048,
    )
    second = normalize_record(
        s3_record(),
        expected_bucket="agentflow-documents",
        ingest_prefix="incoming/",
        allowed_extensions=frozenset({".pdf"}),
        max_object_bytes=2048,
    )

    assert first["workspace_id"] == "workspace-1"
    assert first["source"]["key"] == "incoming/workspace-1/policy one.pdf"
    assert first["source"]["filename"] == "policy one.pdf"
    assert first["source"]["etag"] == "abc123"
    assert first["idempotency_key"] == second["idempotency_key"]


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (s3_record(bucket="another-bucket"), "does not match"),
        (s3_record(key="incoming%2Fworkspace-1%2Fscript.exe"), "is not allowed"),
        (s3_record(key="managed%2Fworkspace-1%2Fpolicy.pdf"), "outside INGEST_PREFIX"),
        (s3_record(key="incoming%2Fbad%2Fextra%2Fpolicy.pdf"), "must match"),
        (s3_record(size=4096), "outside the accepted range"),
    ],
)
def test_normalize_record_rejects_invalid_event(record: dict[str, object], message: str) -> None:
    with pytest.raises(EventValidationError, match=message):
        normalize_record(
            record,
            expected_bucket="agentflow-documents",
            ingest_prefix="incoming/",
            allowed_extensions=frozenset({".pdf"}),
            max_object_bytes=2048,
        )


def test_normalize_record_requires_version_id() -> None:
    record = s3_record()
    s3 = record["s3"]
    assert isinstance(s3, dict)
    object_data = s3["object"]
    assert isinstance(object_data, dict)
    object_data.pop("versionId")

    with pytest.raises(EventValidationError, match="versionId must be a non-empty string"):
        normalize_record(
            record,
            expected_bucket="agentflow-documents",
            ingest_prefix="incoming/",
            allowed_extensions=frozenset({".pdf"}),
            max_object_bytes=2048,
        )


def test_handler_validates_all_records_before_sending() -> None:
    client = SimpleNamespace(send_message_batch=lambda **kwargs: pytest.fail(str(kwargs)))
    boto3 = ModuleType("boto3")
    boto3.client = lambda service: client  # type: ignore[attr-defined]
    event = {
        "Records": [
            s3_record(),
            s3_record(key="incoming%2Fworkspace-1%2Fbad.exe"),
        ]
    }
    environment = {
        "QUEUE_URL": "https://sqs.us-west-2.amazonaws.com/123/jobs",
        "EXPECTED_BUCKET": "agentflow-documents",
        "INGEST_PREFIX": "incoming/",
        "ALLOWED_EXTENSIONS": ".pdf",
        "MAX_OBJECT_BYTES": "2048",
    }

    with (
        patch.dict(os.environ, environment, clear=True),
        patch.dict(sys.modules, {"boto3": boto3}),
        pytest.raises(EventValidationError, match="is not allowed"),
    ):
        lambda_handler(event, None)


def test_handler_rejects_missing_version_before_sqs_send() -> None:
    client = SimpleNamespace(send_message_batch=lambda **kwargs: pytest.fail(str(kwargs)))
    boto3 = ModuleType("boto3")
    boto3.client = lambda service: client  # type: ignore[attr-defined]
    record = s3_record()
    s3 = record["s3"]
    assert isinstance(s3, dict)
    object_data = s3["object"]
    assert isinstance(object_data, dict)
    object_data.pop("versionId")
    environment = {
        "QUEUE_URL": "https://sqs.us-west-2.amazonaws.com/123/jobs",
        "EXPECTED_BUCKET": "agentflow-documents",
        "INGEST_PREFIX": "incoming/",
        "ALLOWED_EXTENSIONS": ".pdf",
        "MAX_OBJECT_BYTES": "2048",
    }

    with (
        patch.dict(os.environ, environment, clear=True),
        patch.dict(sys.modules, {"boto3": boto3}),
        pytest.raises(EventValidationError, match="versionId must be a non-empty string"),
    ):
        lambda_handler({"Records": [record]}, None)


def test_handler_batches_normalized_jobs_for_sqs() -> None:
    calls: list[dict[str, object]] = []

    def send_message_batch(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        entries = kwargs["Entries"]
        assert isinstance(entries, list)
        return {"Successful": [{"Id": item["Id"]} for item in entries]}

    client = SimpleNamespace(send_message_batch=send_message_batch)
    boto3 = ModuleType("boto3")
    boto3.client = lambda service: client  # type: ignore[attr-defined]
    records = [s3_record(key=f"incoming%2Fworkspace-1%2Fpolicy-{index}.pdf") for index in range(11)]
    environment = {
        "QUEUE_URL": "https://sqs.us-west-2.amazonaws.com/123/jobs",
        "EXPECTED_BUCKET": "agentflow-documents",
        "INGEST_PREFIX": "incoming/",
        "ALLOWED_EXTENSIONS": ".pdf,.txt",
        "MAX_OBJECT_BYTES": "2048",
    }

    with (
        patch.dict(os.environ, environment, clear=True),
        patch.dict(sys.modules, {"boto3": boto3}),
    ):
        result = lambda_handler({"Records": records}, None)

    assert result == {"accepted": 11, "queue": "sqs", "schema_version": 1}
    assert [len(call["Entries"]) for call in calls] == [10, 1]
    first_body = json.loads(calls[0]["Entries"][0]["MessageBody"])
    assert first_body["job_type"] == "document.ingest"
    assert first_body["workspace_id"] == "workspace-1"
    assert first_body["source"]["key"] == "incoming/workspace-1/policy-0.pdf"
