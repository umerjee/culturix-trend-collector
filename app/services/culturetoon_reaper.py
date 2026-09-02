"""Marks toons abandoned mid-generation, so a dead worker stops looking busy.

A toon is set to "animating" before generation starts and moved to
"ready"/"failed" by the same in-process background task. If that process
dies — a Railway redeploy restarting the container, a crash, an operator
killing the run — nothing ever moves it again. It sits "animating" forever,
showing a spinner the UI can never resolve.

Confirmed live 2026-09-02: two toons stuck for 23.9h and 45.8h, both
displaying "Generating — this can take a few minutes" indefinitely. A deploy
restarts the container, so any generation in flight at that moment is
orphaned — this is routine, not exceptional.

Deliberately age-based rather than "fail everything animating at startup":
a legitimate render can now run for the better part of an hour (see
MAX_TOTAL_SECONDS and the 3600s job timeouts), and killing a live generation
would be far worse than showing a stale spinner a little longer.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("culturix.services.culturetoon_reaper")

# Comfortably beyond the longest legitimate render. The client gives up on a
# RunPod job at 3600s; anything still "animating" at twice that has no live
# worker behind it.
STALE_AFTER_SECONDS = 2 * 3600


def reap_stale_animating_toons(session, stale_after_seconds: int = STALE_AFTER_SECONDS) -> int:
    """Fails every toon that has been "animating" past the cutoff.

    Marked failed, never "ready", even when the toon already has a
    final_video_url: that URL is from a PREVIOUS successful take, and
    promoting it would report an interrupted generation as a finished one.
    The old video stays viewable — only the status stops lying.

    Returns how many were reaped. Commits its own work.
    """
    from app.models.toon import Toon

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    stale = (
        session.query(Toon)
        .filter(Toon.status == "animating")
        .filter(Toon.updated_at < cutoff)
        .all()
    )
    for toon in stale:
        toon.status = "failed"
        toon.generation_error = (
            "Generation was interrupted before it finished — most likely the server "
            "restarted (a deploy) while it was running. Nothing was charged for the "
            "unfinished part. Press Generate again to retry."
        )
        logger.info("Reaped stale animating toon %s (last updated %s)", toon.id, toon.updated_at)

    if stale:
        session.commit()
    return len(stale)


def run_toon_reaper() -> None:
    """Scheduler entry point."""
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        count = reap_stale_animating_toons(session)
        if count:
            logger.info("Toon reaper marked %d stale generation(s) as failed", count)
    except Exception:
        session.rollback()
        logger.exception("Toon reaper failed")
    finally:
        session.close()
