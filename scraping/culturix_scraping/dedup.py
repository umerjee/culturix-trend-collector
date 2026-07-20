"""
Deduplication layer. Default is in-memory (process-local, resets on restart —
fine for a single spider run). If REDIS_URL is set, dedup persists across runs
and workers via Redis SETs with a TTL, same optional-service pattern the rest
of Culturix uses (QDRANT_URL, RESEND_API_KEY, etc.): missing config degrades
gracefully rather than failing.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

logger = logging.getLogger("culturix.scraping.dedup")

_SEEN_TTL_SECONDS = 7 * 24 * 3600  # a week is enough to catch re-crawls of the same trending feed


class Deduplicator(Protocol):
    async def seen(self, key: str) -> bool: ...
    async def mark(self, key: str) -> None: ...


class InMemoryDeduplicator:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def seen(self, key: str) -> bool:
        return key in self._seen

    async def mark(self, key: str) -> None:
        self._seen.add(key)


class RedisDeduplicator:
    def __init__(self, redis_url: str, ttl_seconds: int = _SEEN_TTL_SECONDS) -> None:
        import redis.asyncio as redis

        self._client = redis.from_url(redis_url)
        self._ttl = ttl_seconds

    async def seen(self, key: str) -> bool:
        return bool(await self._client.exists(f"trend_seen:{key}"))

    async def mark(self, key: str) -> None:
        await self._client.set(f"trend_seen:{key}", "1", ex=self._ttl)


async def build_deduplicator() -> Deduplicator:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return InMemoryDeduplicator()
    try:
        dedup = RedisDeduplicator(redis_url)
        await dedup._client.ping()
        return dedup
    except Exception as e:
        logger.warning("REDIS_URL set but Redis unreachable (%s) — falling back to in-memory dedup", e)
        return InMemoryDeduplicator()
