"""
Fires when an item crosses the velocity threshold. Kept deliberately pluggable
rather than hardcoded to one downstream system: posts a JSON payload to
CONTENT_ENGINE_WEBHOOK_URL if set, otherwise logs a clean structured line so
the hook is visibly working even with nothing wired up yet.

To point this at Culturix's actual content engine (app/pipeline/nodes/
content_strategist.py), the natural target is a new lightweight FastAPI route
in app/main.py that takes this payload and enqueues/kicks off generation for
that trend — that route doesn't exist yet, so CONTENT_ENGINE_WEBHOOK_URL is
unset by default and this just logs.
"""
from __future__ import annotations

import logging
import os

from .items import TrendRecord

logger = logging.getLogger("culturix.scraping.hooks")


async def trigger_content_engine(record: TrendRecord, score: float) -> None:
    payload = {
        "video_id": record.video_id,
        "platform": record.platform,
        "description": record.description[:200],
        "velocity_score": round(score, 2),
        "like_count": record.like_count,
        "view_count": record.view_count,
        "created_at": record.created_at.isoformat(),
    }

    webhook_url = os.getenv("CONTENT_ENGINE_WEBHOOK_URL")
    if not webhook_url:
        logger.info("High-velocity trend (no CONTENT_ENGINE_WEBHOOK_URL configured): %s", payload)
        return

    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info("Dispatched high-velocity trend %s to content engine (%s)", record.video_id, webhook_url)
    except Exception as e:
        logger.error("Failed to notify content engine for %s: %s", record.video_id, e)
