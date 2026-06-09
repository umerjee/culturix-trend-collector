"""
Xiaohongshu / RedNote collector via Apify actor easyapi/xiaohongshu-scraper.
Requires APIFY_API_TOKEN env var.
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger("culturix.collectors.xhs")

DEFAULT_KEYWORDS = ["潮流", "穿搭", "生活方式", "美妆", "健身", "护肤"]


def collect_xhs(keywords: list[str] | None = None, max_items: int = 100) -> list[dict]:
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        logger.warning("APIFY_API_TOKEN not set — skipping Xiaohongshu collection")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("apify-client not installed — run: pip install apify-client")
        return []

    kws = keywords or DEFAULT_KEYWORDS
    client = ApifyClient(token)
    signals = []

    try:
        run = client.actor("easyapi/xiaohongshu-scraper").call(
            run_input={"keywords": kws, "maxItems": max_items, "sortBy": "hot"}
        )
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            text = (item.get("title") or "") + " " + (item.get("desc") or "")
            signals.append({
                "source": "xhs",
                "external_id": item.get("noteId") or item.get("id"),
                "content_text": text.strip(),
                "author": item.get("authorName") or item.get("author"),
                "url": item.get("url") or item.get("noteUrl"),
                "likes": int(item.get("liked") or item.get("likeCount") or 0),
                "comments": int(item.get("comments") or item.get("commentCount") or 0),
                "shares": int(item.get("share") or item.get("shareCount") or 0),
                "hashtags": item.get("tags") or [],
                "language": "zh",
                "region": "CN",
            })
        logger.info("Collected %d signals from Xiaohongshu", len(signals))
    except Exception as e:
        logger.error("Xiaohongshu collection failed: %s", e)

    return signals


def store_xhs_signals(keywords: list[str] | None = None, max_items: int = 100) -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.language import translate_to_english_if_needed

    signals = collect_xhs(keywords, max_items)
    if not signals:
        return 0

    session = SessionLocal()
    inserted = 0
    try:
        for s in signals:
            if not s.get("external_id"):
                continue
            exists = session.query(Trend).filter_by(
                platform="xhs", external_id=s["external_id"]
            ).first()
            if exists:
                continue
            translated = translate_to_english_if_needed(s["content_text"], "zh")
            trend = Trend(
                platform="xhs",
                external_id=s["external_id"],
                title=s["content_text"][:200],
                content=s["content_text"],
                translated_content=translated,
                language="zh",
                url=s.get("url"),
                author=s.get("author"),
                likes=s.get("likes"),
                comments=s.get("comments"),
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
