"""S3-compatible raw object storage adapter."""

from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from agentflow.errors import DependencyUnavailableError, NotFoundError
from agentflow.object_store.base import ObjectMetadata
from agentflow.object_store.local import validate_object_key


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        force_path_style: bool = False,
    ) -> None:
        self._bucket = bucket
        client_options: dict[str, Any] = {
            "service_name": "s3",
            "region_name": region,
            "endpoint_url": endpoint_url,
            "config": Config(s3={"addressing_style": "path" if force_path_style else "auto"}),
        }
        if access_key_id is not None:
            client_options["aws_access_key_id"] = access_key_id
        if secret_access_key is not None:
            client_options["aws_secret_access_key"] = secret_access_key
        self._client = boto3.client(**client_options)

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        checksum_sha256: str,
    ) -> ObjectMetadata:
        validate_object_key(key)
        try:
            response = await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": checksum_sha256},
            )
        except (BotoCoreError, ClientError) as exc:
            raise DependencyUnavailableError("object storage upload failed") from exc
        return ObjectMetadata(
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            etag=str(response.get("ETag", "")).strip('"') or None,
            checksum_sha256=checksum_sha256,
            version_id=response.get("VersionId"),
        )

    async def get(self, key: str, *, version_id: str | None = None) -> bytes:
        validate_object_key(key)
        request: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if version_id is not None:
            request["VersionId"] = version_id
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                **request,
            )
            body = response["Body"]
            try:
                return await asyncio.to_thread(body.read)
            finally:
                body.close()
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise NotFoundError("object not found", details={"key": key}) from exc
            raise DependencyUnavailableError("object storage download failed") from exc
        except BotoCoreError as exc:
            raise DependencyUnavailableError("object storage download failed") from exc

    async def head(self, key: str, *, version_id: str | None = None) -> ObjectMetadata:
        validate_object_key(key)
        request: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if version_id is not None:
            request["VersionId"] = version_id
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                **request,
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise NotFoundError("object not found", details={"key": key}) from exc
            raise DependencyUnavailableError("object storage metadata lookup failed") from exc
        except BotoCoreError as exc:
            raise DependencyUnavailableError("object storage metadata lookup failed") from exc
        metadata = response.get("Metadata", {})
        return ObjectMetadata(
            key=key,
            size_bytes=int(response["ContentLength"]),
            content_type=str(response.get("ContentType", "application/octet-stream")),
            etag=str(response.get("ETag", "")).strip('"') or None,
            checksum_sha256=metadata.get("sha256"),
            version_id=response.get("VersionId"),
        )

    async def delete(self, key: str, *, version_id: str | None = None) -> None:
        validate_object_key(key)
        request: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if version_id is not None:
            request["VersionId"] = version_id
        try:
            await asyncio.to_thread(self._client.delete_object, **request)
        except (BotoCoreError, ClientError) as exc:
            raise DependencyUnavailableError("object storage delete failed") from exc

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
            return True
        except (BotoCoreError, ClientError):
            return False

    async def close(self) -> None:
        self._client.close()
