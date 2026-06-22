"""
Pipeline scheduler — collection runs 4× per day, full digest once per day.
Runs inside the FastAPI process; also triggerable via POST /collect/all for
external cron reliability (recommended: set up a Railway Cron Job or cron-job.org
pointing to POST /collect/all every 6 hours as a belt-and-suspenders backup).
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("culturix.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")


def run_collection():
    """Collect fresh signals from all platforms. Runs 4× per day."""
    logger.info("Collection run starting...")
    try:
        from app.collectors.orchestrator import run_all_collectors
        results = run_all_collectors()
        logger.info("Collection done: %s", results)
    except Exception as e:
        logger.error("Collection failed: %s", e)


def run_daily_pipeline():
    """Full pipeline: collect → translate → embed → cluster → personas → digests.
    Runs once per day at 07:00 UTC so digests are ready for morning use."""
    logger.info("Daily pipeline starting...")

    # 1. Collect (also triggered independently 3 other times per day)
    run_collection()

    # 2. Translate untranslated rows
    try:
        from app.db import SessionLocal
        from app.models.trend import Trend
        from app.language import detect_language, translate_to_english_if_needed

        session = SessionLocal()
        try:
            untranslated = (
                session.query(Trend)
                .filter(Trend.translated_content.is_(None))
                .order_by(Trend.id.desc())
                .limit(2000)
                .all()
            )
            for t in untranslated:
                text = t.content or t.title or ""
                if not text.strip():
                    continue
                t.language = detect_language(text)
                t.translated_content = translate_to_english_if_needed(text, t.language)
            session.commit()
            logger.info("Translation done (%d rows)", len(untranslated))
        finally:
            session.close()
    except Exception as e:
        logger.error("Translation failed: %s", e)

    # 3. Embed
    try:
        from app.embedding_processor import process_embeddings
        n = process_embeddings(limit=1000)
        logger.info("Embedded %d new trends", n)
    except Exception as e:
        logger.error("Embedding failed: %s", e)

    # 4. Cluster
    try:
        from app.clustering_service import run_clustering
        result = run_clustering(limit=1000, min_cluster_size=2)
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
    # Collect 4× per day: 01:00, 07:00, 13:00, 19:00 UTC
    for hour in (1, 13, 19):
        scheduler.add_job(
            run_collection,
            CronTrigger(hour=hour, minute=0),
            id=f"collect_{hour:02d}h",
        )
    # Full digest pipeline once per day at 07:00 UTC (morning run includes collection)
    scheduler.add_job(run_daily_pipeline, CronTrigger(hour=7, minute=0), id="daily_pipeline")
    scheduler.start()
    logger.info("Scheduler started — collection at 01:00/07:00/13:00/19:00 UTC, full pipeline at 07:00 UTC")


def stop():
    scheduler.shutdown(wait=False)
