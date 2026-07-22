"""
Master orchestrator — runs all collectors in sequence and returns totals.
Called by the Railway cron tier 1 every 2 hours.
"""
import logging
import os

logger = logging.getLogger("culturix.orchestrator")


def run_all_collectors() -> dict:
    results = {}

    # Reddit
    try:
        from app.collectors.reddit import store_reddit_trends
        results["reddit"] = store_reddit_trends()
        logger.info("Reddit: %d inserted", results["reddit"])
    except Exception as e:
        logger.error("Reddit failed: %s", e)
        results["reddit"] = 0

    # TikTok
    try:
        from app.collectors.tiktok import store_tiktok_trends
        results["tiktok"] = store_tiktok_trends(region="US")
        logger.info("TikTok: %d inserted", results["tiktok"])
    except Exception as e:
        logger.error("TikTok failed: %s", e)
        results["tiktok"] = 0

    # YouTube
    try:
        from app.collectors.youtube import store_youtube_trends, fetch_youtube_trending
        probe = fetch_youtube_trending("US", limit=1)
        results["youtube"] = store_youtube_trends("US") if probe else 0
        logger.info("YouTube: %d inserted", results["youtube"])
    except Exception as e:
        logger.error("YouTube failed: %s", e)
        results["youtube"] = 0

    # Xiaohongshu (Apify)
    try:
        from app.collectors.xiaohongshu import store_xhs_signals
        results["xhs"] = store_xhs_signals()
        logger.info("Xiaohongshu: %d inserted", results["xhs"])
    except Exception as e:
        logger.error("Xiaohongshu failed: %s", e)
        results["xhs"] = 0

    # Twitter — prefer Apify, fall back to proxy
    try:
        if os.getenv("APIFY_API_TOKEN"):
            from app.collectors.twitter_apify import store_twitter_apify
            results["twitter"] = store_twitter_apify()
        else:
            from app.collectors.twitter_fallback import store_twitter_trends_via_proxy
            results["twitter"] = store_twitter_trends_via_proxy("us")
        logger.info("Twitter: %d inserted", results["twitter"])
    except Exception as e:
        logger.error("Twitter failed: %s", e)
        results["twitter"] = 0

    # Pinterest (Apify) — only runs if APIFY_API_TOKEN is set
    try:
        from app.collectors.pinterest import store_pinterest_signals
        results["pinterest"] = store_pinterest_signals()
        logger.info("Pinterest: %d inserted", results["pinterest"])
    except Exception as e:
        logger.error("Pinterest failed: %s", e)
        results["pinterest"] = 0

    # Wikipedia trending pageviews — free, no auth, no approval process.
    # Added as a "world trends" source since Reddit's API now requires a
    # multi-week approval process (its collector stays in place, dormant,
    # in case that approval ever comes through).
    try:
        from app.collectors.wikipedia import store_wikipedia_trends
        results["wikipedia"] = store_wikipedia_trends()
        logger.info("Wikipedia: %d inserted", results["wikipedia"])
    except Exception as e:
        logger.error("Wikipedia failed: %s", e)
        results["wikipedia"] = 0

    # Bluesky trending topics — free, no auth, official public API
    try:
        from app.collectors.bluesky import store_bluesky_trends
        results["bluesky"] = store_bluesky_trends()
        logger.info("Bluesky: %d inserted", results["bluesky"])
    except Exception as e:
        logger.error("Bluesky failed: %s", e)
        results["bluesky"] = 0

    # Instagram — hashtag search via ScrapeCreators, only runs if
    # SCRAPE_CREATORS_API_KEY is set (store_instagram_trends no-ops otherwise)
    try:
        from app.collectors.instagram import store_instagram_trends
        results["instagram"] = store_instagram_trends()
        logger.info("Instagram: %d inserted", results["instagram"])
    except Exception as e:
        logger.error("Instagram failed: %s", e)
        results["instagram"] = 0

    total = sum(results.values())
    logger.info("Collection complete. Total inserted: %d | breakdown: %s", total, results)
    return {"total": total, **results}


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    print(run_all_collectors())
