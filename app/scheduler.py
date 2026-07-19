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
    """Full pipeline, orchestrated by LangGraph (app.pipeline.graph):
    collect → translate → embed → cluster+persist → personas → content → digests.
    Runs once per day at 07:00 UTC so digests are ready for morning use."""
    logger.info("Daily pipeline starting...")

    # Collect (also triggered independently 3 other times per day)
    run_collection()

    try:
        from app.pipeline.graph import run_pipeline
        result = run_pipeline()
        logger.info(
            "Daily pipeline complete. Clusters: %d, users processed: %d, errors: %s",
            len(result.get("clusters", [])),
            len(result.get("generated_content", [])),
            result.get("errors", []),
        )
    except Exception as e:
        logger.error("Daily pipeline failed: %s", e)


def run_content_check():
    """Daily audit of previously generated content ideas — flags stale ones.
    Runs once per day at 09:00 UTC, after the content engine has run."""
    logger.info("Content Check starting...")
    try:
        from app.pipeline.nodes.content_check import run_content_check as _run_check
        result = _run_check()
        logger.info("Content Check done: %s", result)
    except Exception as e:
        logger.error("Content Check failed: %s", e)


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
    # Content Check — audit prior content for staleness once per day at 09:00 UTC
    scheduler.add_job(run_content_check, CronTrigger(hour=9, minute=0), id="content_check")
    scheduler.start()
    logger.info(
        "Scheduler started — collection at 01:00/07:00/13:00/19:00 UTC, "
        "full pipeline at 07:00 UTC, content check at 09:00 UTC"
    )


def stop():
    scheduler.shutdown(wait=False)
