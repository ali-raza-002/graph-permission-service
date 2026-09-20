"""Check result caches.

Keys always embed the store, model id and snapshot revision. Data at a given revision
never changes, so entries never need invalidation; TTL and LRU only bound memory.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from warden.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    errors: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class CheckCache(Protocol):
    stats: CacheStats

    async def get(self, key: str) -> bool | None: ...

    async def set(self, key: str, value: bool) -> None: ...

    async def close(self) -> None: ...


def namespace(store_id: str, model_id: str, revision: int) -> str:
    return f"warden:check:{store_id}:{model_id}:{revision}:"


@dataclass
class NullCache:
    stats: CacheStats = field(default_factory=CacheStats)

    async def get(self, key: str) -> bool | None:
        self.stats.misses += 1
        return None

    async def set(self, key: str, value: bool) -> None:
        return None

    async def close(self) -> None:
        return None


class MemoryCache:
    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        self._entries: OrderedDict[str, tuple[bool, float]] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self.stats = CacheStats()

    async def get(self, key: str) -> bool | None:
        entry = self._entries.get(key)
        if entry is None or entry[1] < time.monotonic():
            if entry is not None:
                del self._entries[key]
            self.stats.misses += 1
            return None
        self._entries.move_to_end(key)
        self.stats.hits += 1
        return entry[0]

    async def set(self, key: str, value: bool) -> None:
        self._entries[key] = (value, time.monotonic() + self._ttl)
        self._entries.move_to_end(key)
        self.stats.writes += 1
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    async def close(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


class RedisCache:
    """Shared cache across API replicas. Failures degrade to a miss, never an error."""

    def __init__(self, client: Redis, *, ttl_seconds: int) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self.stats = CacheStats()

    @classmethod
    def from_url(cls, url: str, *, ttl_seconds: int) -> RedisCache:
        return cls(Redis.from_url(url, socket_timeout=0.25), ttl_seconds=ttl_seconds)

    async def get(self, key: str) -> bool | None:
        try:
            raw = await self._client.get(key)
        except (RedisError, OSError) as exc:
            self.stats.errors += 1
            log.warning("cache_get_failed", error=str(exc))
            return None
        if raw is None:
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        return bool(raw == b"1")

    async def set(self, key: str, value: bool) -> None:
        try:
            await self._client.set(key, b"1" if value else b"0", ex=self._ttl)
            self.stats.writes += 1
        except (RedisError, OSError) as exc:
            self.stats.errors += 1
            log.warning("cache_set_failed", error=str(exc))

    async def close(self) -> None:
        await self._client.aclose()
