"""
Bridges an already-finished Apify dataset into TrendVelocityPipeline. This is
a standalone batch script, not a Scrapy spider — reading a dataset that
already exists (APIFY_DATASET_ID) rather than triggering a fresh actor run
is the cheap path (no new actor-run cost), and there's no crawling involved,
so it drives the pipeline directly via asyncio instead of `scrapy crawl`.

Actor-agnostic: maps the handful of field-name variants used across the
popular TikTok/Instagram scraper actors on Apify's store (playCount vs
viewCount, diggCount vs likeCount, createTimeISO vs takenAtTimestamp, etc.)
onto the TrendItem shape TrendRecord.from_item expects. Matches the same
apify-client usage already established in app/collectors/xiaohongshu.py and
app/collectors/twitter_apify.py.

Usage:
    APIFY_API_TOKEN=... APIFY_DATASET_ID=... python -m culturix_scraping.collectors.trend_apify_ingestor
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import urlparse

from scrapy import Spider
from scrapy.exceptions import DropItem

from ..pipelines import TrendVelocityPipeline

logger = logging.getLogger("culturix.scraping.trend_apify_ingestor")

# This script drives TrendVelocityPipeline directly, outside Scrapy's crawl
# engine — nothing in open_spider/process_item/close_spider reads attributes
# off `spider`, they just pass it through per Scrapy's ItemPipeline
# interface, so a typed None stand-in is accurate here rather than a
# misleading fake object.
_NO_SPIDER = cast(Spider, None)

_PLATFORM_HOSTS = {
    "tiktok.com": "tiktok",
    "instagram.com": "instagram",
}


def _infer_platform(item: dict[str, Any]) -> str | None:
    explicit = os.getenv("APIFY_PLATFORM")
    if explicit:
        return explicit.strip().lower()

    for key in ("platform", "source"):
        value = item.get(key)
        if value:
            return str(value).strip().lower()

    url = item.get("webVideoUrl") or item.get("url") or item.get("postUrl") or ""
    host = urlparse(str(url)).netloc.lower()
    for suffix, platform in _PLATFORM_HOSTS.items():
        if host.endswith(suffix):
            return platform
    return None


def _parse_created_at(item: dict[str, Any]) -> datetime | None:
    for key in ("createTimeISO", "timestamp", "created_at", "publishedAt"):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue

    for key in ("createTime", "takenAtTimestamp", "taken_at"):
        value = item.get(key)
        if isinstance(value, (int, float)) and value:
            return datetime.fromtimestamp(value, tz=timezone.utc)

    return None


def _first_int(item: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = item.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def map_apify_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Maps one raw Apify dataset row onto the shape TrendRecord.from_item
    expects. Returns None (rather than raising) for a row missing what we
    need to identify it — the caller counts and logs skips over failing
    the whole batch on one bad row."""
    video_id = str(
        item.get("id") or item.get("videoId") or item.get("video_id")
        or item.get("postId") or item.get("shortCode") or item.get("code") or ""
    ).strip()
    if not video_id:
        return None

    platform = _infer_platform(item)
    if not platform:
        return None

    created_at = _parse_created_at(item)
    if created_at is None:
        return None

    description = (
        item.get("text") or item.get("desc") or item.get("description")
        or item.get("caption") or item.get("title") or ""
    )

    return {
        "video_id": video_id,
        "platform": platform,
        "description": str(description),
        "view_count": _first_int(item, "playCount", "viewCount", "view_count", "videoViewCount"),
        "like_count": _first_int(item, "diggCount", "likeCount", "likesCount", "like_count"),
        "share_count": _first_int(item, "shareCount", "share_count"),
        "comment_count": _first_int(item, "commentCount", "comment_count"),
        "created_at": created_at,
    }


def _iter_dataset_items() -> Iterable[dict[str, Any]]:
    token = os.environ["APIFY_API_TOKEN"]
    dataset_id = os.environ["APIFY_DATASET_ID"]

    try:
        from apify_client import ApifyClient
    except ImportError as e:
        raise RuntimeError("apify-client not installed — run: pip install apify-client") from e

    client = ApifyClient(token)
    yield from client.dataset(dataset_id).iterate_items()


async def ingest() -> dict[str, int]:
    """Reads APIFY_DATASET_ID end to end through TrendVelocityPipeline: dedup,
    velocity scoring, async upsert into the same `trends` table the main
    backend reads from. Returns counters for whoever's watching the run."""
    pipeline = TrendVelocityPipeline()
    await pipeline.open_spider(_NO_SPIDER)

    mapped = 0
    unmappable = 0
    dropped = 0
    errored = 0

    try:
        for raw_item in _iter_dataset_items():
            mapped_item = map_apify_item(raw_item)
            if mapped_item is None:
                unmappable += 1
                continue
            mapped += 1

            try:
                await pipeline.process_item(mapped_item, _NO_SPIDER)
            except DropItem as e:
                dropped += 1
                logger.debug("Dropped: %s", e)
            except Exception:
                errored += 1
                logger.exception("Failed to process item %s", mapped_item.get("video_id"))
    finally:
        await pipeline.close_spider(_NO_SPIDER)

    stats = {"mapped": mapped, "unmappable": unmappable, "dropped": dropped, "errored": errored}
    logger.info("Apify ingest complete: %s", stats)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    for required in ("APIFY_API_TOKEN", "APIFY_DATASET_ID"):
        if not os.getenv(required):
            raise SystemExit(f"{required} is required")
    asyncio.run(ingest())


if __name__ == "__main__":
    main()
