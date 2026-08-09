"""Concurrency-safe in-memory cache for local mode and tests."""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any


class InMemoryJsonCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get_json(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= time.monotonic():
                self._values.pop(key, None)
                return None
            return copy.deepcopy(value)

    async def set_json(self, key: str, value: dict[str, Any], *, ttl_seconds: int) -> None:
        async with self._lock:
            self._values[key] = (time.monotonic() + ttl_seconds, copy.deepcopy(value))

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._values.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        async with self._lock:
            self._values.clear()
