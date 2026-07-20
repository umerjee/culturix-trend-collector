"""
Bridges ScrapeCreators' hashtag-search API into TrendVelocityPipeline. Same
downstream pipeline as trend_apify_ingestor.py (dedup, velocity scoring,
async Postgres upsert) — only the fetch-and-map layer differs. No actor-run/
dataset lifecycle here, just a direct async HTTP GET per search term via
httpx, authenticated with a single x-api-key header.

Field names below are grounded against ScrapeCreators' published docs
(docs.scrapecreators.com/v1/tiktok/search/hashtag and .../instagram/search/
hashtag), not guessed — but the Apify integration needed a live-data fix for
exactly this reason (an actor's actual output didn't match its docs), so
treat this the same way: verify against one real response before trusting it
in production. Specifically uncertain: Instagram's top-level response
wrapper key isn't shown in the docs excerpt available when this was written
— _extract_items() tries several common candidates and logs a warning if
none match, rather than silently returning nothing.

TikTok hashtag search nests engagement stats under `statistics` and posts
`create_time` as Unix epoch seconds. Instagram uses flat fields, `taken_at`
as ISO 8601, and has no share_count field at all (defaults to 0).

Usage:
    SCRAPE_CREATORS_API_KEY=... SCRAPE_CREATORS_SEARCH_TERMS="ai,startups" \
      python -m culturix_scraping.collectors.trend_scrapecreators_ingestor
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, cast

from scrapy import Spider
from scrapy.exceptions import DropItem

from ..pipelines import TrendVelocityPipeline

logger = logging.getLogger("culturix.scraping.trend_scrapecreators_ingestor")

_BASE_URL = "https://api.scrapecreators.com"
_ENDPOINTS = {
    "tiktok": "/v1/tiktok/search/hashtag",
    "instagram": "/v1/instagram/search/hashtag",
}
# Confirmed against docs for tiktok (aweme_list). Not confirmed for
# instagram — see module docstring — so it's left unset and _extract_items
# falls through to trying common candidates instead.
_KNOWN_LIST_KEY = {
    "tiktok": "aweme_list",
}

# Same "this drives the pipeline outside Scrapy's crawl engine" reasoning as
# trend_apify_ingestor.py — nothing in these pipeline methods reads `spider`.
_NO_SPIDER = cast(Spider, None)


def _extract_items(platform: str, payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    known_key = _KNOWN_LIST_KEY.get(platform)
    if known_key and isinstance(payload.get(known_key), list):
        return payload[known_key]

    for candidate in ("aweme_list", "data", "posts", "items", "results"):
        if isinstance(payload.get(candidate), list):
            return payload[candidate]

    logger.warning(
        "Could not find an item list in %s response (tried known key %r + common candidates); "
        "top-level keys were: %s", platform, known_key, sorted(payload.keys()),
    )
    return []


def _first_int(item: dict[str, Any], *paths: str) -> int:
    """paths may use 'a.b' for one level of nesting (e.g. TikTok's statistics.digg_count)."""
    for path in paths:
        node: Any = item
        for part in path.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        if isinstance(node, (int, float)):
            return int(node)
    return 0


def _parse_created_at(item: dict[str, Any]) -> datetime | None:
    for key in ("taken_at", "created_at", "publishedAt"):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue

    for key in ("create_time", "createTime", "taken_at_timestamp"):
        value = item.get(key)
        if isinstance(value, (int, float)) and value:
            return datetime.fromtimestamp(value, tz=timezone.utc)

    return None


def map_scrapecreators_item(platform: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """Maps one raw ScrapeCreators result item onto the shape TrendRecord.
    from_item expects. Returns None for a row missing what we need to
    identify it, rather than raising — the caller counts and logs skips."""
    video_id = str(item.get("aweme_id") or item.get("id") or item.get("shortcode") or "").strip()
    if not video_id:
        return None

    created_at = _parse_created_at(item)
    if created_at is None:
        return None

    description = str(item.get("desc") or item.get("caption") or item.get("text") or "")

    return {
        "video_id": video_id,
        "platform": platform,
        "description": description,
        "view_count": _first_int(item, "statistics.play_count", "video_view_count", "video_play_count", "play_count"),
        "like_count": _first_int(item, "statistics.digg_count", "like_count", "digg_count"),
        "share_count": _first_int(item, "statistics.share_count", "share_count"),
        "comment_count": _first_int(item, "statistics.comment_count", "comment_count"),
        "created_at": created_at,
    }


async def _fetch_search_results(client: "Any", platform: str, term: str, max_pages: int) -> list[dict[str, Any]]:
    api_key = os.environ["SCRAPE_CREATORS_API_KEY"]
    endpoint = _ENDPOINTS.get(platform)
    if not endpoint:
        raise ValueError(f"Unsupported SCRAPE_CREATORS_PLATFORM: {platform!r} (expected 'tiktok' or 'instagram')")

    all_items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(max_pages):
        params: dict[str, str] = {"hashtag": term}
        if cursor:
            params["cursor"] = cursor

        resp = await client.get(
            f"{_BASE_URL}{endpoint}",
            params=params,
            headers={"x-api-key": api_key},
            timeout=15.0,
        )
        resp.raise_for_status()
        payload = resp.json()

        items = _extract_items(platform, payload)
        if not items:
            break
        all_items.extend(items)

        cursor = payload.get("cursor") if isinstance(payload, dict) else None
        if not cursor:
            break

    return all_items


async def ingest() -> dict[str, int]:
    """Reads SCRAPE_CREATORS_SEARCH_TERMS end to end through
    TrendVelocityPipeline: dedup, velocity scoring, async upsert into the
    same `trends` table the main backend reads from."""
    import httpx

    platform = os.getenv("SCRAPE_CREATORS_PLATFORM", "tiktok").strip().lower()
    terms = [t.strip() for t in os.environ["SCRAPE_CREATORS_SEARCH_TERMS"].split(",") if t.strip()]
    max_pages = int(os.getenv("SCRAPE_CREATORS_MAX_PAGES", "1"))
    if not terms:
        raise RuntimeError("SCRAPE_CREATORS_SEARCH_TERMS is required (comma-separated hashtags/keywords)")

    pipeline = TrendVelocityPipeline()
    await pipeline.open_spider(_NO_SPIDER)

    mapped = unmappable = dropped = errored = 0

    try:
        async with httpx.AsyncClient() as client:
            for term in terms:
                logger.info("Fetching %s hashtag search for %r...", platform, term)
                try:
                    raw_items = await _fetch_search_results(client, platform, term, max_pages)
                except Exception:
                    logger.exception("Fetch failed for term %r — skipping", term)
                    continue
                logger.info("Got %d raw items for %r", len(raw_items), term)

                for raw_item in raw_items:
                    mapped_item = map_scrapecreators_item(platform, raw_item)
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
    logger.info("ScrapeCreators ingest complete: %s", stats)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    for required in ("SCRAPE_CREATORS_API_KEY", "SCRAPE_CREATORS_SEARCH_TERMS"):
        if not os.getenv(required):
            raise SystemExit(f"{required} is required")
    asyncio.run(ingest())


if __name__ == "__main__":
    main()
