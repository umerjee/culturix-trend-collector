"""
Bluesky trending topics collector — official public AT Protocol API.
Completely free, no API key, no auth at all (public unauthenticated endpoint).

app.bsky.unspecced.getTrends already gives richer structure than most
sources here: real-time postCount, a hot/rising status, and a category,
straight from Bluesky's own trend-detection.
"""
import logging
from datetime import datetime

import httpx

logger = logging.getLogger("culturix.collectors.bluesky")

_URL = "https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrends"


def fetch_trends() -> list:
    try:
        resp = httpx.get(_URL, timeout=15.0)
        resp.raise_for_status()
        return resp.json().get("trends", [])
    except Exception as e:
        logger.warning("Bluesky trends fetch failed: %s", e)
        return []


def store_bluesky_trends(limit: int = 30) -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend

    trends = fetch_trends()[:limit]
    if not trends:
        return 0

    session = SessionLocal()
    inserted = 0
    today = datetime.utcnow().date().isoformat()

    try:
        for t in trends:
            topic_key = t.get("topic")
            display = t.get("displayName") or topic_key
            if not topic_key:
                continue

            external_id = f"bluesky:{today}:{topic_key}"
            exists = session.query(Trend).filter_by(
                platform="bluesky", external_id=external_id
            ).first()
            if exists:
                continue

            post_count = t.get("postCount", 0)
            status = t.get("status", "")
            category = t.get("category", "")
            content = f"{display} is trending on Bluesky ({status}, {post_count} posts)"
            if category:
                content += f" — category: {category}"

            trend = Trend(
                platform="bluesky",
                external_id=external_id,
                url=f"https://bsky.app{t.get('link', '')}" if t.get("link") else None,
                title=display,
                content=content,
                translated_content=content,
                language="en",
                likes=post_count,
                raw_json={k: v for k, v in t.items() if k != "actors"},  # drop verbose actor profiles
            )
            session.add(trend)
            try:
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
