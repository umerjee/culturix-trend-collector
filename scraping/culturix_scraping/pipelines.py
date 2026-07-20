"""
TrendVelocityPipeline — dedup -> velocity scoring -> Postgres upsert ->
high-velocity hook, for whatever spider you wire up later.

Requires the asyncio Twisted reactor and pipeline registration in your
Scrapy project's settings.py:

    TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
    ITEM_PIPELINES = {"culturix_scraping.pipelines.TrendVelocityPipeline": 300}
    VELOCITY_THRESHOLD = 500.0  # optional override, likes/hour-equivalent

See ../README.md for required env vars (DATABASE_URL, optionally REDIS_URL
and CONTENT_ENGINE_WEBHOOK_URL) and the one-time schema setup.
"""
from __future__ import annotations

import logging
from typing import Any

from scrapy import Spider
from scrapy.exceptions import DropItem

from .db import AsyncSessionLocal, dispose_engine, upsert_trend
from .dedup import Deduplicator, build_deduplicator
from .hooks import trigger_content_engine
from .items import TrendRecord
from .velocity import DEFAULT_VELOCITY_THRESHOLD, is_high_velocity, velocity_score

logger = logging.getLogger("culturix.scraping.pipeline")


class TrendVelocityPipeline:
    def __init__(self, velocity_threshold: float = DEFAULT_VELOCITY_THRESHOLD) -> None:
        self.velocity_threshold = velocity_threshold
        self.dedup: Deduplicator | None = None
        self._processed = 0
        self._duplicates = 0
        self._high_velocity = 0

    @classmethod
    def from_crawler(cls, crawler) -> "TrendVelocityPipeline":
        threshold = crawler.settings.getfloat("VELOCITY_THRESHOLD", DEFAULT_VELOCITY_THRESHOLD)
        return cls(velocity_threshold=threshold)

    async def open_spider(self, spider: Spider) -> None:
        self.dedup = await build_deduplicator()
        logger.info("TrendVelocityPipeline open (threshold=%.1f)", self.velocity_threshold)

    async def close_spider(self, spider: Spider) -> None:
        await dispose_engine()
        logger.info(
            "TrendVelocityPipeline closed — processed=%d duplicates=%d high_velocity=%d",
            self._processed, self._duplicates, self._high_velocity,
        )

    async def process_item(self, item: dict[str, Any], spider: Spider) -> dict[str, Any]:
        try:
            record = TrendRecord.from_item(item)
        except ValueError as e:
            raise DropItem(f"Malformed item, dropping: {e}") from e

        dedup_key = f"{record.platform}:{record.video_id}"
        if await self.dedup.seen(dedup_key):
            self._duplicates += 1
            raise DropItem(f"Duplicate: {dedup_key}")
        await self.dedup.mark(dedup_key)

        score = velocity_score(record.like_count, record.created_at)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await upsert_trend(session, {
                    "platform": record.platform,
                    "external_id": record.video_id,
                    "content": record.description,
                    "title": record.description[:200],
                    "likes": record.like_count,
                    "comments": record.comment_count,
                    "shares": record.share_count,
                    "views": record.view_count,
                    "posted_at": record.created_at,
                    "velocity_score": score,
                    "raw_json": dict(item),
                })

        self._processed += 1
        if is_high_velocity(score, self.velocity_threshold):
            self._high_velocity += 1
            await trigger_content_engine(record, score)

        item["velocity_score"] = score
        return item
