"""
Pinterest Trends collector via Apify actor seibs.co/pinterest-trends-intel.
Requires APIFY_API_TOKEN env var. Uses "trend_search" mode — returns trend
records (keyword, trajectory, growth %, related terms), not raw pins.
"""
import os
import logging

logger = logging.getLogger("culturix.collectors.pinterest")

DEFAULT_KEYWORDS = [
    "home decor", "fashion trends", "outfit inspo", "aesthetic",
    "recipes", "self care", "wedding ideas", "hairstyles",
]


def collect_pinterest(keywords: list[str] | None = None, region: str = "US", max_items: int = 25) -> list[dict]:
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        logger.warning("APIFY_API_TOKEN not set — skipping Pinterest collection")
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
        run = client.actor("seibs.co/pinterest-trends-intel").call(
            run_input={
                "mode": "trend_search",
                "keywords": kws,
                "region": region,
                "max_pins_per_query": max_items,
            }
        )
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            # This actor emits trend/pin/creator_signal/topic_rollup records in
            # one dataset — we only want the trend records here.
            keyword = item.get("keyword")
            if not keyword:
                continue

            related = item.get("related_terms") or []
            trend_type = item.get("trend_type", "")
            text = f"{keyword} is a {trend_type} Pinterest trend".strip()
            if related:
                text += f". Related: {', '.join(related[:5])}"

            signals.append({
                "source": "pinterest",
                "external_id": f"{region}:{keyword}",
                "content_text": text,
                "likes": int(item.get("interest_latest") or 0),
                "region": region,
                "raw": item,
            })
        logger.info("Collected %d signals from Pinterest", len(signals))
    except Exception as e:
        logger.error("Pinterest collection failed: %s", e)

    return signals


def store_pinterest_signals(keywords: list[str] | None = None, region: str = "US", max_items: int = 25) -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend

    signals = collect_pinterest(keywords, region, max_items)
    if not signals:
        return 0

    session = SessionLocal()
    inserted = 0
    try:
        for s in signals:
            exists = session.query(Trend).filter_by(
                platform="pinterest", external_id=s["external_id"]
            ).first()
            if exists:
                continue

            trend = Trend(
                platform="pinterest",
                external_id=s["external_id"],
                title=s["content_text"][:200],
                content=s["content_text"],
                translated_content=s["content_text"],  # trend keywords are already English
                language="en",
                likes=s.get("likes"),
                raw_json=s.get("raw"),
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
