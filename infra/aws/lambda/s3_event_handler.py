"""Validate S3 object events and enqueue normalized AgentFlow ingestion jobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import unquote_plus


class EventValidationError(ValueError):
    """Raised when an incoming S3 record is outside the ingestion contract."""


_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _allowed_extensions(raw: str) -> frozenset[str]:
    values = {
        item.strip().casefold() if item.strip().startswith(".") else f".{item.strip().casefold()}"
        for item in raw.split(",")
        if item.strip()
    }
    if not values:
        raise RuntimeError("ALLOWED_EXTENSIONS must contain at least one extension")
    return frozenset(values)


def normalize_record(
    record: Mapping[str, Any],
    *,
    expected_bucket: str,
    ingest_prefix: str,
    allowed_extensions: frozenset[str],
    max_object_bytes: int,
) -> dict[str, Any]:
    """Return a queue-safe job or reject the record before any external write."""

    if record.get("eventSource") != "aws:s3":
        raise EventValidationError("record eventSource must be aws:s3")
    event_name = _required_string(record.get("eventName"), "eventName")
    if not event_name.startswith("ObjectCreated:"):
        raise EventValidationError("only ObjectCreated S3 events are accepted")

    s3 = record.get("s3")
    if not isinstance(s3, Mapping):
        raise EventValidationError("record.s3 must be an object")
    bucket_data = s3.get("bucket")
    object_data = s3.get("object")
    if not isinstance(bucket_data, Mapping) or not isinstance(object_data, Mapping):
        raise EventValidationError("record.s3 bucket and object must be objects")

    bucket = _required_string(bucket_data.get("name"), "s3.bucket.name")
    if bucket != expected_bucket:
        raise EventValidationError("event bucket does not match EXPECTED_BUCKET")

    encoded_key = _required_string(object_data.get("key"), "s3.object.key")
    key = unquote_plus(encoded_key)
    if not key or "\x00" in key:
        raise EventValidationError("decoded S3 object key is invalid")
    normalized_prefix = ingest_prefix.strip("/") + "/"
    if not key.startswith(normalized_prefix):
        raise EventValidationError("S3 object key is outside INGEST_PREFIX")
    relative_key = key.removeprefix(normalized_prefix)
    parts = relative_key.split("/")
    if len(parts) != 2:
        raise EventValidationError(
            "S3 object key must match incoming/{workspace_id}/{filename.ext}"
        )
    workspace_id, filename = parts
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise EventValidationError("S3 object key contains an invalid workspace_id")
    if not filename or filename in {".", ".."}:
        raise EventValidationError("S3 object key contains an invalid filename")
    suffix = "." + filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if suffix not in allowed_extensions:
        raise EventValidationError(f"object extension {suffix or '<none>'} is not allowed")

    try:
        size_bytes = int(object_data.get("size"))
    except (TypeError, ValueError) as exc:
        raise EventValidationError("s3.object.size must be an integer") from exc
    if size_bytes <= 0 or size_bytes > max_object_bytes:
        raise EventValidationError("S3 object size is outside the accepted range")

    etag = _required_string(object_data.get("eTag"), "s3.object.eTag").strip('"')
    sequencer = _required_string(object_data.get("sequencer"), "s3.object.sequencer")
    version_id = _required_string(object_data.get("versionId"), "s3.object.versionId")

    region = _required_string(record.get("awsRegion"), "awsRegion")
    event_time = _required_string(record.get("eventTime"), "eventTime")
    identity_payload = json.dumps(
        {
            "bucket": bucket,
            "etag": etag,
            "key": key,
            "sequencer": sequencer,
            "version_id": version_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    idempotency_key = hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "job_type": "document.ingest",
        "workspace_id": workspace_id,
        "idempotency_key": idempotency_key,
        "occurred_at": event_time,
        "source": {
            "provider": "s3",
            "region": region,
            "bucket": bucket,
            "key": key,
            "filename": filename,
            "version_id": version_id,
            "etag": etag,
            "size_bytes": size_bytes,
            "sequencer": sequencer,
            "event_name": event_name,
        },
    }


def _chunks(items: list[dict[str, str]], size: int) -> Iterable[list[dict[str, str]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """Validate the complete event, then forward jobs to SQS in bounded batches."""

    del context
    queue_url = _required_string(os.environ.get("QUEUE_URL"), "QUEUE_URL")
    expected_bucket = _required_string(os.environ.get("EXPECTED_BUCKET"), "EXPECTED_BUCKET")
    ingest_prefix = _required_string(os.environ.get("INGEST_PREFIX"), "INGEST_PREFIX")
    extensions = _allowed_extensions(os.environ.get("ALLOWED_EXTENSIONS", ""))
    try:
        max_object_bytes = int(os.environ.get("MAX_OBJECT_BYTES", ""))
    except ValueError as exc:
        raise RuntimeError("MAX_OBJECT_BYTES must be an integer") from exc
    if max_object_bytes <= 0:
        raise RuntimeError("MAX_OBJECT_BYTES must be positive")

    records = event.get("Records")
    if not isinstance(records, list) or not records:
        raise EventValidationError("event must contain at least one S3 record")

    jobs = [
        normalize_record(
            record,
            expected_bucket=expected_bucket,
            ingest_prefix=ingest_prefix,
            allowed_extensions=extensions,
            max_object_bytes=max_object_bytes,
        )
        for record in records
    ]

    entries = [
        {
            "Id": f"job-{index}",
            "MessageBody": json.dumps(job, sort_keys=True, separators=(",", ":")),
            "MessageAttributes": {
                "job_type": {
                    "DataType": "String",
                    "StringValue": "document.ingest",
                },
                "schema_version": {
                    "DataType": "Number",
                    "StringValue": "1",
                },
            },
        }
        for index, job in enumerate(jobs)
    ]

    import boto3

    sqs = boto3.client("sqs")
    sent = 0
    for batch in _chunks(entries, 10):
        response = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
        failed = response.get("Failed", [])
        if failed:
            failed_ids = ", ".join(str(item.get("Id")) for item in failed)
            raise RuntimeError(f"SQS rejected normalized jobs: {failed_ids}")
        sent += len(response.get("Successful", []))
    if sent != len(entries):
        raise RuntimeError("SQS response did not confirm every normalized job")

    return {"accepted": len(jobs), "queue": "sqs", "schema_version": 1}
