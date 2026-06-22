import httpx
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language, translate_to_english_if_needed

TIKTOK_TRENDING_URL = "https://www.tikwm.com/api/feed/list/"
TIKTOK_REGIONS = ["US", "GB", "IN", "JP", "KR", "FR", "DE", "BR"]


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
                external_id = item.get("id")
                if not external_id or external_id in seen_in_run:
                    continue
                seen_in_run.add(external_id)

                exists = session.query(Trend).filter_by(
                    platform="tiktok", external_id=external_id
                ).first()
                if exists:
                    continue

                content = item.get("desc") or ""
                lang = detect_language(content)
                translated = translate_to_english_if_needed(content, lang)

                trend = Trend(
                    platform="tiktok",
                    external_id=external_id,
                    url=item.get("share_url"),
                    title=item.get("title") or "",
                    content=content,
                    translated_content=translated,
                    language=lang,
                    author=item.get("author", {}).get("unique_id"),
                    likes=item.get("digg_count"),
                    comments=item.get("comment_count"),
                    posted_at=datetime.fromtimestamp(item.get("create_time", 0), tz=timezone.utc).replace(tzinfo=None),
                    raw_json=item,
                )
                session.add(trend)
                inserted += 1

        session.commit()
        return inserted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
