"""Filesystem object storage for local development."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath

from agentflow.errors import NotFoundError, UnsafeDocumentError
from agentflow.object_store.base import ObjectMetadata


def validate_object_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if not key or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeDocumentError("invalid object key")
    if "\\" in key or "\x00" in key:
        raise UnsafeDocumentError("invalid object key")
    return path


class LocalObjectStore:
    """Atomic local storage whose keys cannot escape its configured root."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = self._root.joinpath(*validate_object_key(key).parts).resolve()
        if not path.is_relative_to(self._root):
            raise UnsafeDocumentError("object key escapes storage root")
        return path

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        checksum_sha256: str,
    ) -> ObjectMetadata:
        actual_checksum = hashlib.sha256(data).hexdigest()
        if actual_checksum != checksum_sha256:
            raise UnsafeDocumentError("object checksum does not match upload")
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
            try:
                with os.fdopen(file_descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)

        await asyncio.to_thread(write)
        return ObjectMetadata(
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            etag=actual_checksum,
            checksum_sha256=actual_checksum,
        )

    async def get(self, key: str, *, version_id: str | None = None) -> bytes:
        del version_id
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise NotFoundError("object not found", details={"key": key}) from exc

    async def head(self, key: str, *, version_id: str | None = None) -> ObjectMetadata:
        del version_id
        path = self._path(key)
        try:
            stat = await asyncio.to_thread(path.stat)
        except FileNotFoundError as exc:
            raise NotFoundError("object not found", details={"key": key}) from exc
        return ObjectMetadata(
            key=key,
            size_bytes=stat.st_size,
            content_type="application/octet-stream",
        )

    async def delete(self, key: str, *, version_id: str | None = None) -> None:
        del version_id
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return

    async def ping(self) -> bool:
        return await asyncio.to_thread(self._root.is_dir)

    async def close(self) -> None:
        return None
