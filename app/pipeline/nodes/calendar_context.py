"""Loads upcoming cultural/religious/political events (app/services/
calendar_events.py) onto pipeline state so content_strategist.py can write
ideas that anticipate what's coming, not just react to what's already
trending — e.g. a Diwali-themed idea two weeks before Diwali, not two
weeks after.

Deliberately NOT filtered per-profile here: a ContentProfile's
target_regions is one of several loosely-related targeting fields (see
load_signals in graph.py) and this node runs once for the whole pipeline
run, not per-profile — narrowing to "relevant to ANY tracked region" and
letting the LLM in content_strategist.py judge per-idea relevance mirrors
how top_signals/clusters are already handled (state-wide context, profile-
specific selection happens in the prompt, not the query).

Fail-open, same posture as trend_historian.py: a calendar outage must
never take down the daily pipeline, just leave ideas without event
awareness for that run.
"""
import logging

from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.calendar_context")

# How far ahead an event is worth planning content around — long enough to
# actually publish ahead of the date, short enough that "upcoming" still
# means something (a 6-month-out election isn't yet a content trigger).
LOOKAHEAD_DAYS = 45


def load_upcoming_events(state: PipelineState) -> PipelineState:
    from app.db import SessionLocal
    from app.services.calendar_events import get_upcoming_events

    session = SessionLocal()
    try:
        events = get_upcoming_events(session, lookahead_days=LOOKAHEAD_DAYS)
        state["upcoming_events"] = [
            {
                "name": e.name,
                "category": e.category,
                "date": e.date.isoformat(),
                "regions": e.regions or [],
                "description": e.description,
            }
            for e in events
        ]
        logger.info("Loaded %d upcoming event(s) within %d days", len(state["upcoming_events"]), LOOKAHEAD_DAYS)
    except Exception as e:
        logger.warning("Could not load upcoming events — continuing without them: %s", e)
        state["errors"] = state.get("errors", []) + [f"calendar_context: {e}"]
        state["upcoming_events"] = []
    finally:
        session.close()

    return state
