"""Tiny async-safe TTL cache.

Used to avoid hammering the market-data API and to keep response times low.
Intentionally dependency-free (in-memory). Swap for Redis in production by
keeping the same ``get``/``set`` interface.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, default_ttl: int = 15) -> None:
        self._default_ttl = default_ttl
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires_at, value = item
            if time.monotonic() > expires_at:
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        async with self._lock:
            self._store[key] = (time.monotonic() + (ttl or self._default_ttl), value)

    async def get_or_set(
        self, key: str, factory: Callable[[], Awaitable[T]], ttl: int | None = None
    ) -> T:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        await self.set(key, value, ttl)
        return value


cache = TTLCache()
