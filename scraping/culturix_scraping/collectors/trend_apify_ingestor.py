"""
Bridges Apify into TrendVelocityPipeline. This is a standalone batch script,
not a Scrapy spider — there's no crawling involved, so it drives the
pipeline directly via asyncio instead of `scrapy crawl`.

Two ways to get a dataset (see _resolve_dataset_id):
  - APIFY_DATASET_ID: read an already-finished dataset, no new run cost.
    Cheapest option, but static — re-running this against the same dataset
    ID just re-ingests the same data, since a dataset is a snapshot of one
    past run, not a live feed.
  - APIFY_ACTOR_ID + APIFY_SEARCH_TERMS (+ optional APIFY_MAX_ITEMS): trigger
    a fresh actor run each time this is invoked. Required for recurring/
    scheduled use (see ../../run_scheduled_ingest.py) — this is what makes
    "run this every 6 hours" mean anything instead of a no-op after the
    first run.

Actor-agnostic: maps the handful of field-name variants used across the
popular TikTok/Instagram/Twitter scraper actors on Apify's store (playCount
vs viewCount, diggCount vs likeCount, createTimeISO vs takenAtTimestamp,
etc.) onto the TrendItem shape TrendRecord.from_item expects. Matches the
same apify-client usage already established in app/collectors/xiaohongshu.py
and app/collectors/twitter_apify.py.

Usage:
    APIFY_API_TOKEN=... APIFY_DATASET_ID=... \
      python -m culturix_scraping.collectors.trend_apify_ingestor

    APIFY_API_TOKEN=... APIFY_ACTOR_ID=apidojo/tweet-scraper APIFY_SEARCH_TERMS="ai,startups" \
      python -m culturix_scraping.collectors.trend_apify_ingestor
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
    "twitter.com": "twitter",
    "x.com": "twitter",
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


_TWITTER_LEGACY_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"  # e.g. "Mon Jul 20 11:56:36 +0000 2026"


def _parse_created_at(item: dict[str, Any]) -> datetime | None:
    for key in ("createTimeISO", "timestamp", "created_at", "publishedAt", "createdAt"):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
            try:
                # apidojo/tweet-scraper (and Twitter's classic API) use this
                # format for createdAt, not ISO 8601 — e.g. "Mon Jul 20
                # 11:56:36 +0000 2026". Confirmed against a live dataset row.
                return datetime.strptime(value, _TWITTER_LEGACY_DATE_FORMAT)
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
        item.get("id") or item.get("tweetId") or item.get("videoId") or item.get("video_id")
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
        item.get("text") or item.get("fullText") or item.get("desc") or item.get("description")
        or item.get("caption") or item.get("title") or ""
    )

    return {
        "video_id": video_id,
        "platform": platform,
        "description": str(description),
        "view_count": _first_int(item, "playCount", "viewCount", "view_count", "videoViewCount"),
        "like_count": _first_int(item, "diggCount", "likeCount", "likesCount", "like_count", "favoriteCount"),
        "share_count": _first_int(item, "shareCount", "share_count", "retweetCount"),
        "comment_count": _first_int(item, "commentCount", "comment_count", "replyCount"),
        "created_at": created_at,
    }


def _get_client() -> "Any":
    token = os.environ["APIFY_API_TOKEN"]
    try:
        from apify_client import ApifyClient
    except ImportError as e:
        raise RuntimeError("apify-client not installed — run: pip install apify-client") from e
    return ApifyClient(token)


def _trigger_actor_run(client: "Any", actor_id: str, search_terms: list[str], max_items: int) -> str:
    """Triggers a fresh actor run and returns its dataset_id. This is what
    makes recurring scheduling meaningful for Apify — reading a fixed
    APIFY_DATASET_ID (the cheap, default path) would just re-ingest the same
    dataset forever on a schedule, since Apify datasets are static snapshots
    of a past run, not a live feed."""
    logger.info("Triggering Apify actor %s (maxItems=%d, terms=%s)...", actor_id, max_items, search_terms)
    run = client.actor(actor_id).call(run_input={
        "searchTerms": search_terms,
        "maxItems": max_items,
        "sort": "Latest",
        "lang": "",
    })
    if not run:
        raise RuntimeError(f"Apify actor run for {actor_id!r} returned no result")
    # Attribute access, not dict-subscript — apify-client's Run object isn't
    # subscriptable (see app/collectors/twitter_apify.py's own note on this).
    dataset_id = run.default_dataset_id
    logger.info("Actor run complete. dataset_id=%s", dataset_id)
    return dataset_id


def _resolve_dataset_id(client: "Any") -> str:
    dataset_id = os.getenv("APIFY_DATASET_ID")
    if dataset_id:
        return dataset_id

    actor_id = os.getenv("APIFY_ACTOR_ID")
    search_terms_raw = os.getenv("APIFY_SEARCH_TERMS")
    if actor_id and search_terms_raw:
        search_terms = [t.strip() for t in search_terms_raw.split(",") if t.strip()]
        max_items = int(os.getenv("APIFY_MAX_ITEMS", "60"))
        return _trigger_actor_run(client, actor_id, search_terms, max_items)

    raise RuntimeError(
        "Set either APIFY_DATASET_ID (read an existing dataset, no run cost) "
        "or both APIFY_ACTOR_ID and APIFY_SEARCH_TERMS (trigger a fresh run — "
        "required for recurring/scheduled use, since a dataset is a static "
        "snapshot of one past run, not a live feed)"
    )


def _iter_dataset_items() -> Iterable[dict[str, Any]]:
    client = _get_client()
    dataset_id = _resolve_dataset_id(client)
    yield from client.dataset(dataset_id).iterate_items()


async def ingest() -> dict[str, int]:
    """Reads from APIFY_DATASET_ID (or triggers a fresh run via APIFY_ACTOR_ID
    + APIFY_SEARCH_TERMS) end to end through TrendVelocityPipeline: dedup,
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
    if not os.getenv("APIFY_API_TOKEN"):
        raise SystemExit("APIFY_API_TOKEN is required")
    has_dataset = bool(os.getenv("APIFY_DATASET_ID"))
    has_actor_run = bool(os.getenv("APIFY_ACTOR_ID")) and bool(os.getenv("APIFY_SEARCH_TERMS"))
    if not has_dataset and not has_actor_run:
        raise SystemExit(
            "Set either APIFY_DATASET_ID, or both APIFY_ACTOR_ID and APIFY_SEARCH_TERMS"
        )
    asyncio.run(ingest())


if __name__ == "__main__":
    main()
