"""Cache protocol for disposable JSON values."""

from __future__ import annotations

from typing import Any, Protocol


class JsonCache(Protocol):
    async def get_json(self, key: str) -> dict[str, Any] | None: ...

    async def set_json(self, key: str, value: dict[str, Any], *, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...
