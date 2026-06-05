"""
Daily pipeline scheduler.
Runs automatically at 02:00 UTC every day when the FastAPI server is up.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("culturix.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")


def run_daily_pipeline():
    logger.info("Daily pipeline starting...")
    results = {}

    # 1. Collect
    try:
        from app.collectors.twitter_fallback import store_twitter_trends_via_proxy
        from app.collectors.tiktok import store_tiktok_trends
        from app.collectors.youtube import store_youtube_trends, fetch_youtube_trending
        from app.collectors.reddit import store_reddit_trends

        results["twitter"] = store_twitter_trends_via_proxy("us")
        results["tiktok"] = store_tiktok_trends(region="US")
        results["reddit"] = store_reddit_trends()

        probe = fetch_youtube_trending("US", limit=1)
        results["youtube"] = store_youtube_trends("US") if probe else 0

        logger.info("Collection done: %s", results)
    except Exception as e:
        logger.error("Collection failed: %s", e)

    # 2. Translate
    try:
        from app.db import SessionLocal
        from app.models.trend import Trend
        from app.language import detect_language, translate_to_english_if_needed

        session = SessionLocal()
        try:
            trends = session.query(Trend).order_by(Trend.id.desc()).limit(1000).all()
            for t in trends:
                text = t.content or t.title or ""
                if not text.strip():
                    continue
                lang = detect_language(text)
                t.language = lang
                t.translated_content = translate_to_english_if_needed(text, lang)
            session.commit()
            logger.info("Translation done")
        finally:
            session.close()
    except Exception as e:
        logger.error("Translation failed: %s", e)

    # 3. Embed
    try:
        from app.embedding_processor import process_embeddings
        n = process_embeddings(limit=500)
        logger.info("Embedded %d new trends", n)
    except Exception as e:
        logger.error("Embedding failed: %s", e)

    # 4. Cluster
    try:
        from app.clustering_service import run_clustering
        result = run_clustering(limit=500, min_cluster_size=2)
        logger.info("Clustering done: %s", result)
    except Exception as e:
        logger.error("Clustering failed: %s", e)

    # 5. Personas
    try:
        from app.personas import generate_clustered_personas
        result = generate_clustered_personas()
        logger.info("Personas done: %s", result)
    except Exception as e:
        logger.error("Persona generation failed: %s", e)

    logger.info("Daily pipeline complete.")


def start():
    # Run every day at 02:00 UTC
    scheduler.add_job(run_daily_pipeline, CronTrigger(hour=2, minute=0), id="daily_pipeline")
    scheduler.start()
    logger.info("Scheduler started — daily pipeline at 02:00 UTC")


def stop():
    scheduler.shutdown(wait=False)
