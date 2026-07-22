"""Instagram collector — via ScrapeCreators' hashtag-search API, not raw
scraping (no proxy rotation/bot-evasion code here, matching this codebase's
scraping/ subproject's own documented scope). Ported from the previously
unwired scraping/culturix_scraping/collectors/trend_scrapecreators_ingestor.py
— that ingestor's field-mapping assumptions were live-verified against a
real `#fashion` hashtag search response before this port: top-level `posts`
key, flat `caption` string, ISO `taken_at`, `like_count`/`comment_count`/
`video_view_count` present, no `share_count` field at all.

Instagram has no official "trending" feed (unlike YouTube's official API or
TikTok's tikwm.com proxy) — ScrapeCreators only offers hashtag/keyword
search, not a firehose. INSTAGRAM_HASHTAGS is a small set of broad,
evergreen discovery hashtags standing in for a general trending pulse,
matching the un-personalized, broad-collection role every other collector
plays here — real personalization happens downstream in persona_mapper.py,
not at collection time.
"""
import httpx
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language

INSTAGRAM_SEARCH_URL = "https://api.scrapecreators.com/v1/instagram/search/hashtag"
INSTAGRAM_HASHTAGS = ["viral", "trending", "fyp", "explorepage"]


def fetch_instagram_hashtag(hashtag: str, api_key: str, max_pages: int = 1) -> list:
    all_items = []
    cursor = None
    for _ in range(max_pages):
        params = {"hashtag": hashtag}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = httpx.get(
                INSTAGRAM_SEARCH_URL, params=params,
                headers={"x-api-key": api_key}, timeout=20.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            break

        items = payload.get("posts") if isinstance(payload, dict) else None
        if not items:
            break
        all_items.extend(items)

        cursor = payload.get("cursor") if isinstance(payload, dict) else None
        if not cursor:
            break

    return all_items


def _cache_instagram_media(item: dict, external_id: str) -> str | None:
    """Instagram's display_url/thumbnail_src are signed, time-expiring CDN
    URLs (confirmed live — an `oe=` hex expiry param, same characteristic as
    TikTok's cover URLs) — must be downloaded and re-hosted at collection
    time, not stored directly. Mirrors app/collectors/tiktok.py's
    _cache_cover_image exactly. Fails open (returns None) on any error."""
    media_url = item.get("display_url") or item.get("thumbnail_src")
    if not media_url:
        return None
    try:
        resp = httpx.get(media_url, timeout=15.0)
        resp.raise_for_status()
        from app.media import storage
        return storage.upload(resp.content, f"trend-thumbnails/instagram/{external_id}.jpg", "image/jpeg")
    except Exception:
        return None


def _parse_taken_at(item: dict) -> datetime | None:
    value = item.get("taken_at")
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def store_instagram_trends(hashtags=None, limit_per_hashtag: int = 30) -> int:
    import os
    api_key = os.getenv("SCRAPE_CREATORS_API_KEY")
    if not api_key:
        return 0

    hashtags = hashtags or INSTAGRAM_HASHTAGS
    session = SessionLocal()
    inserted = 0

    try:
        seen_in_run: set[str] = set()
        for hashtag in hashtags:
            items = fetch_instagram_hashtag(hashtag, api_key)[:limit_per_hashtag]
            for item in items:
                external_id = str(item.get("id") or item.get("pk") or item.get("shortcode") or "").strip()
                if not external_id or external_id in seen_in_run:
                    continue
                seen_in_run.add(external_id)

                taken_at = _parse_taken_at(item)
                if taken_at is None:
                    continue

                exists = session.query(Trend).filter_by(
                    platform="instagram", external_id=external_id
                ).first()
                if exists:
                    continue

                content = item.get("caption") or ""
                lang = detect_language(content)
                owner = item.get("owner") or {}

                trend = Trend(
                    platform="instagram",
                    external_id=external_id,
                    url=item.get("url") or (f"https://www.instagram.com/reel/{item.get('shortcode')}/" if item.get("shortcode") else None),
                    title=None,
                    content=content,
                    translated_content=None,
                    language=lang,
                    author=owner.get("username"),
                    likes=item.get("like_count"),
                    comments=item.get("comment_count"),
                    views=item.get("video_view_count") or item.get("play_count") or None,
                    posted_at=taken_at,
                    raw_json=item,
                    region=None,  # hashtag search has no region concept — unknown, not excluded
                    image_url=_cache_instagram_media(item, external_id),
                )
                session.add(trend)
                try:
                    # Commit per row — same SQLAlchemy batched-insert/JSON
                    # adaptation issue found and fixed in the TikTok/Reddit
                    # collectors (many session.add() calls before one big
                    # commit can fail on the dict raw_json column).
                    session.commit()
                    inserted += 1
                except Exception:
                    session.rollback()

        return inserted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    print(store_instagram_trends())
