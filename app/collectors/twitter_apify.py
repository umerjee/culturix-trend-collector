"""
Twitter / X collector via Apify actor apidojo/tweet-scraper.
More reliable than the official API at this scale.
Requires APIFY_API_TOKEN env var.
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger("culturix.collectors.twitter_apify")

DEFAULT_QUERIES = [
    "trending now -is:retweet",
    "viral today -is:retweet",
    "breaking culture -is:retweet",
]


def collect_twitter_apify(queries: list[str] | None = None, max_items: int = 200) -> list[dict]:
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        logger.warning("APIFY_API_TOKEN not set — skipping Twitter/Apify collection")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("apify-client not installed — run: pip install apify-client")
        return []

    qrs = queries or DEFAULT_QUERIES
    client = ApifyClient(token)
    signals = []

    try:
        run = client.actor("apidojo/tweet-scraper").call(
            run_input={
                "searchTerms": qrs,
                "maxItems": max_items,
                "sort": "Latest",
                "lang": "",  # all languages
            }
        )
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            signals.append({
                "source": "twitter",
                "external_id": str(item.get("id") or item.get("tweetId") or ""),
                "content_text": item.get("text") or item.get("fullText") or "",
                "author": item.get("author", {}).get("userName") if isinstance(item.get("author"), dict) else item.get("authorName"),
                "url": item.get("url") or f"https://x.com/i/web/status/{item.get('id')}",
                "likes": int(item.get("likeCount") or item.get("favoriteCount") or 0),
                "comments": int(item.get("replyCount") or 0),
                "shares": int(item.get("retweetCount") or 0),
                "views": int(item.get("viewCount") or 0),
                "hashtags": [h.get("text", "") for h in (item.get("entities") or {}).get("hashtags", [])],
                "language": item.get("lang") or "en",
                "region": None,
            })
        logger.info("Collected %d tweets via Apify", len(signals))
    except Exception as e:
        logger.error("Twitter/Apify collection failed: %s", e)

    return signals


def store_twitter_apify(queries: list[str] | None = None, max_items: int = 200) -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.language import detect_language, translate_to_english_if_needed

    signals = collect_twitter_apify(queries, max_items)
    if not signals:
        return 0

    session = SessionLocal()
    inserted = 0
    try:
        for s in signals:
            if not s.get("external_id"):
                continue
            exists = session.query(Trend).filter_by(
                platform="twitter", external_id=s["external_id"]
            ).first()
            if exists:
                continue
            lang = detect_language(s["content_text"])
            translated = translate_to_english_if_needed(s["content_text"], lang)
            trend = Trend(
                platform="twitter",
                external_id=s["external_id"],
                title=s["content_text"][:200],
                content=s["content_text"],
                translated_content=translated,
                language=lang,
                url=s.get("url"),
                author=s.get("author"),
                likes=s.get("likes"),
                comments=s.get("comments"),
                views=s.get("views"),
                raw_json=s,
            )
            session.add(trend)
            inserted += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return inserted
