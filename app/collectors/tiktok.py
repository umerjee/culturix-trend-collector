import httpx
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language
from app.collectors.region_codes import normalize_region

TIKTOK_TRENDING_URL = "https://www.tikwm.com/api/feed/list/"
TIKTOK_REGIONS = ["US", "GB", "IN", "JP", "KR", "FR", "DE", "BR"]


def _cache_cover_image(item: dict, external_id: str) -> str | None:
    """TikTok's cover URLs are signed and time-expiring (x-expires= param) —
    unusable if fetched later, so re-host to Supabase Storage now to get a
    durable URL. Fails open (returns None) on any error: tikwm.com is already
    an unofficial/unstable proxy elsewhere in this codebase, and a failed
    thumbnail cache should never block the trend row itself from being stored."""
    cover_url = item.get("origin_cover") or item.get("cover")
    if not cover_url:
        return None
    try:
        resp = httpx.get(cover_url, timeout=15.0)
        resp.raise_for_status()
        from app.media import storage
        return storage.upload(resp.content, f"trend-thumbnails/tiktok/{external_id}.jpg", "image/jpeg")
    except Exception:
        return None


def fetch_tiktok_trending(count=50, region="US"):
    params = {"count": count, "region": region}
    try:
        resp = httpx.get(TIKTOK_TRENDING_URL, params=params, timeout=15.0)
        j = resp.json()
    except Exception:
        return []
    if resp.status_code != 200 or not j or "data" not in j:
        return []
    return j.get("data", [])


def store_tiktok_trends(limit=50, region="US"):
    regions = TIKTOK_REGIONS if region == "US" else [region]
    session = SessionLocal()
    inserted = 0

    try:
        seen_in_run: set[str] = set()
        for r in regions:
            items = fetch_tiktok_trending(limit, r)
            for item in items:
                # tikwm.com's response uses "video_id"/"title" today, not the
                # "id"/"desc"/"share_url" fields this used to read — those were
                # always None, so every row got silently skipped below.
                external_id = item.get("video_id") or item.get("id")
                if not external_id or external_id in seen_in_run:
                    continue
                seen_in_run.add(external_id)

                exists = session.query(Trend).filter_by(
                    platform="tiktok", external_id=external_id
                ).first()
                if exists:
                    continue

                content = item.get("desc") or item.get("title") or ""
                music = item.get("music_info") or {}
                music_title = music.get("title")
                if music_title:
                    content = f"{content} [Audio: {music_title}" + (
                        f" by {music['author']}]" if music.get("author") else "]"
                    )
                lang = detect_language(content)

                author_handle = item.get("author", {}).get("unique_id")
                url = item.get("share_url")
                if not url and author_handle:
                    url = f"https://www.tiktok.com/@{author_handle}/video/{external_id}"

                trend = Trend(
                    platform="tiktok",
                    external_id=external_id,
                    url=url,
                    title=(item.get("title") or "")[:200],
                    content=content,
                    translated_content=None,
                    language=lang,
                    author=author_handle,
                    likes=item.get("digg_count"),
                    comments=item.get("comment_count"),
                    posted_at=datetime.fromtimestamp(item.get("create_time", 0), tz=timezone.utc).replace(tzinfo=None),
                    raw_json=item,
                    region=normalize_region(r),
                    image_url=_cache_cover_image(item, external_id),
                )
                session.add(trend)
                try:
                    # Commit per row: SQLAlchemy 2.0's batched multi-row insert
                    # (insertmany_values) can fail to adapt dict raw_json when
                    # many rows are flushed in one statement — committing one
                    # at a time avoids that batching path and isolates a bad
                    # row from the rest of the run.
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
