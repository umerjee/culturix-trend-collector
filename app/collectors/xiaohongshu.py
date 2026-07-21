"""
Xiaohongshu / RedNote collector via Apify actor
easyapi/all-in-one-rednote-xiaohongshu-scraper. Requires APIFY_API_TOKEN.

Replaces the previous easyapi/xiaohongshu-scraper reference, which started
failing with "Actor with this name was not found" — looks like it was
renamed/replaced on Apify's store. This actor requires an explicit `mode`
and nests fields under item.note_card.* rather than flat fields.
"""
import os
import logging
from typing import Optional

logger = logging.getLogger("culturix.collectors.xhs")

DEFAULT_KEYWORDS = ["潮流", "穿搭", "生活方式", "美妆", "健身", "护肤"]
_ACTOR = "easyapi/all-in-one-rednote-xiaohongshu-scraper"
_MIN_ITEMS = 30  # actor enforces this floor


def collect_xhs(keywords: Optional[list] = None, max_items: int = 100) -> list:
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
        run = client.actor(_ACTOR).call(
            run_input={
                "mode": "search",
                "keywords": kws,
                "maxItems": max(max_items, _MIN_ITEMS),
            }
        )
        if not run:
            logger.error("Xiaohongshu actor run returned no result")
            return []
        for row in client.dataset(run.default_dataset_id).iterate_items():
            item = row.get("item") or row
            note = item.get("note_card") or {}
            title = note.get("display_title") or note.get("title") or ""
            desc = note.get("desc") or note.get("display_desc") or note.get("description") or ""
            text = f"{title} {desc}".strip()
            if not text:
                continue

            interact = note.get("interact_info") or {}
            user = note.get("user") or {}

            signals.append({
                "source": "xhs",
                "external_id": item.get("id") or item.get("note_id"),
                "content_text": text,
                "author": user.get("nick_name") or user.get("nickname"),
                "url": row.get("link"),
                "likes": int(interact.get("liked_count") or 0),
                "comments": int(interact.get("comment_count") or 0),
                "shares": int(interact.get("share_count") or 0),
                "hashtags": note.get("tag_list") or [],
                "language": "zh",
                "region": "CN",
            })
        logger.info("Collected %d signals from Xiaohongshu", len(signals))
    except Exception as e:
        logger.error("Xiaohongshu collection failed: %s", e)

    return signals


def store_xhs_signals(keywords: Optional[list] = None, max_items: int = 100) -> int:
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
                region="CN",  # Xiaohongshu is a fixed China-only market
            )
            session.add(trend)
            try:
                # Commit per row — same SQLAlchemy batched-insert/JSON
                # adaptation issue found and fixed in other collectors.
                session.commit()
                inserted += 1
            except Exception:
                session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return inserted
