"""
Optional standalone scheduler for the ingestors in
culturix_scraping/collectors/ — reads a cron-style schedule from env vars
and runs whichever ingestor(s) are enabled, forever, as its own process.

Deliberately NOT wired into the main backend's in-process scheduler
(app/scheduler.py): doing so would mean bundling scrapy/asyncpg/apify-client
into the deployed backend's dependency footprint, which was kept separate on
purpose (see README.md's Scope section — this package isn't part of the
deployed backend). Run this as its own process instead: locally in a
terminal, as a separate Railway service, or under any process manager
(systemd, pm2, supervisord) — whichever you already use for long-running
workers.

Each ingestor is independently opt-in via its own env var, so you can run
one, both, or neither without touching this file:

    SCHEDULE_APIFY=true
    APIFY_API_TOKEN=...
    APIFY_ACTOR_ID=apidojo/tweet-scraper     # required for recurring runs — see
    APIFY_SEARCH_TERMS=ai,startups           # trend_apify_ingestor.py's docstring
    APIFY_CRON_HOUR=*/6                      # APScheduler cron syntax, default */6

    SCHEDULE_SCRAPECREATORS=true
    SCRAPE_CREATORS_API_KEY=...
    SCRAPE_CREATORS_SEARCH_TERMS=ai,startups
    SCRAPE_CREATORS_PLATFORM=tiktok           # tiktok (default) / instagram / threads
    SCRAPE_CREATORS_CRON_HOUR=*/6

Usage (from the scraping/ directory, or anywhere with it on PYTHONPATH):
    PYTHONPATH=<repo-root> python run_scheduled_ingest.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so culturix_scraping resolves when run directly

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("culturix.scraping.scheduler")

_DEFAULT_CRON_HOUR = "*/6"


def _run_apify() -> None:
    logger.info("Scheduled Apify ingest starting...")
    try:
        from culturix_scraping.collectors.trend_apify_ingestor import ingest
        stats = asyncio.run(ingest())
        logger.info("Scheduled Apify ingest done: %s", stats)
    except Exception:
        logger.exception("Scheduled Apify ingest failed")


def _run_scrapecreators() -> None:
    logger.info("Scheduled ScrapeCreators ingest starting...")
    try:
        from culturix_scraping.collectors.trend_scrapecreators_ingestor import ingest
        stats = asyncio.run(ingest())
        logger.info("Scheduled ScrapeCreators ingest done: %s", stats)
    except Exception:
        logger.exception("Scheduled ScrapeCreators ingest failed")


def register_jobs(scheduler: Any) -> int:
    """Returns the number of jobs registered — separated from main() so the
    env-var-driven registration logic is testable without actually starting
    a blocking scheduler."""
    jobs_added = 0

    if os.getenv("SCHEDULE_APIFY", "").strip().lower() == "true":
        hour = os.getenv("APIFY_CRON_HOUR", _DEFAULT_CRON_HOUR)
        scheduler.add_job(_run_apify, CronTrigger(hour=hour, minute=0), id="apify_ingest")
        logger.info("Apify ingest scheduled: hour=%s", hour)
        jobs_added += 1

    if os.getenv("SCHEDULE_SCRAPECREATORS", "").strip().lower() == "true":
        hour = os.getenv("SCRAPE_CREATORS_CRON_HOUR", _DEFAULT_CRON_HOUR)
        scheduler.add_job(_run_scrapecreators, CronTrigger(hour=hour, minute=0), id="scrapecreators_ingest")
        logger.info("ScrapeCreators ingest scheduled: hour=%s", hour)
        jobs_added += 1

    return jobs_added


def main() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    jobs_added = register_jobs(scheduler)

    if jobs_added == 0:
        raise SystemExit(
            "Nothing scheduled — set SCHEDULE_APIFY=true and/or SCHEDULE_SCRAPECREATORS=true"
        )

    logger.info("Scheduler starting with %d job(s)...", jobs_added)
    scheduler.start()


if __name__ == "__main__":
    main()
