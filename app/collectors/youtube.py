import httpx
import re
from datetime import datetime
import os

from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language
from app.collectors.region_codes import normalize_region

YOUTUBE_TRENDING_URL = "https://www.googleapis.com/youtube/v3/videos"


def _fetch_via_scrape(limit: int) -> list:
    try:
        page = httpx.get("https://www.youtube.com/feed/trending", timeout=15.0).text
        ids = []
        for m in re.finditer(r"/watch\?v=([A-Za-z0-9_-]{11})", page):
            vid = m.group(1)
            if vid not in ids:
                ids.append(vid)
            if len(ids) >= limit:
                break
        items = []
        for vid in ids:
            try:
                o = httpx.get(
                    "https://www.youtube.com/oembed",
                    params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
                    timeout=10.0,
                ).json()
                items.append({
                    "id": vid,
                    "snippet": {
                        "title": o.get("title", ""),
                        "publishedAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "description": "",
                        "channelTitle": o.get("author_name", ""),
                    },
                    "statistics": {},
                })
            except Exception:
                continue
        return items
    except Exception:
        return []


def fetch_youtube_trending(region="US", limit=30):
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        print("[YouTube API] YOUTUBE_API_KEY not set — going straight to scrape fallback")
        return _fetch_via_scrape(limit)

    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": limit,
        "key": key,
    }
    try:
        resp = httpx.get(YOUTUBE_TRENDING_URL, params=params, timeout=15.0)
        if not resp.is_success:
            err = resp.json().get("error", {})
            reasons = [e.get("reason") for e in err.get("errors", [])]
            print(f"[YouTube API] HTTP {resp.status_code}: {err.get('message')} — reasons: {reasons}")
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as _api_exc:
        print(f"[YouTube API] Primary call failed: {_api_exc}. Trying scrape fallback...")
        return _fetch_via_scrape(limit)


# IT/ES/PT added alongside FR/DE/GB so persona_mapper.py's "EU" target-region
# mapping has real collectors actually tagging those countries, not just
# filter-permission with nothing behind it — see that file's _REGION_LABEL_TO_CODES.
YOUTUBE_REGIONS = ["US", "GB", "IN", "CA", "AU", "FR", "DE", "BR", "JP", "KR", "IT", "ES", "PT"]


def store_youtube_trends(region="US", limit=50):
    """Fetch trending videos across multiple regions to maximise unique signal coverage."""
    regions = YOUTUBE_REGIONS if region == "US" else [region]
    session = SessionLocal()
    inserted = 0
    try:
        seen_in_run: set[str] = set()
        for r in regions:
            items = fetch_youtube_trending(r, limit)
            for item in items:
                if item["id"] in seen_in_run:
                    continue
                seen_in_run.add(item["id"])

                exists = session.query(Trend).filter_by(
                    platform="youtube", external_id=item["id"]
                ).first()
                if exists:
                    continue

                snippet = item["snippet"]
                stats = item.get("statistics", {})
                content = snippet.get("description") or ""
                lang = detect_language(content)

                trend = Trend(
                    platform="youtube",
                    external_id=item["id"],
                    url=f"https://www.youtube.com/watch?v={item['id']}",
                    title=snippet.get("title"),
                    content=content,
                    translated_content=None,
                    language=lang,
                    author=snippet.get("channelTitle"),
                    likes=stats.get("likeCount"),
                    comments=stats.get("commentCount"),
                    posted_at=datetime.strptime(snippet["publishedAt"], "%Y-%m-%dT%H:%M:%SZ"),
                    raw_json=item,
                    region=normalize_region(r),
                    image_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
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
