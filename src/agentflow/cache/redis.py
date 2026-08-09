"""Redis JSON cache adapter."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from agentflow.errors import DependencyUnavailableError


class RedisJsonCache:
    def __init__(self, url: str) -> None:
        self._redis: Redis = Redis.from_url(url, decode_responses=False)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            raw = await self._redis.get(key)
        except RedisError as exc:
            raise DependencyUnavailableError("cache lookup failed") from exc
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            await self.delete(key)
            raise DependencyUnavailableError("cache value is invalid") from exc
        if not isinstance(parsed, dict):
            await self.delete(key)
            return None
        return parsed

    async def set_json(self, key: str, value: dict[str, Any], *, ttl_seconds: int) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            await self._redis.set(key, payload, ex=ttl_seconds)
        except RedisError as exc:
            raise DependencyUnavailableError("cache write failed") from exc

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except RedisError as exc:
            raise DependencyUnavailableError("cache delete failed") from exc

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except RedisError:
            return False

    async def close(self) -> None:
        await self._redis.aclose()
