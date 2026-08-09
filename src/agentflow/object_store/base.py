"""Object storage protocol."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ObjectMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    size_bytes: int = Field(ge=0)
    content_type: str
    etag: str | None = None
    checksum_sha256: str | None = None
    version_id: str | None = None


class ObjectStore(Protocol):
    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        checksum_sha256: str,
    ) -> ObjectMetadata: ...

    async def get(self, key: str, *, version_id: str | None = None) -> bytes: ...

    async def head(self, key: str, *, version_id: str | None = None) -> ObjectMetadata: ...

    async def delete(self, key: str, *, version_id: str | None = None) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...
