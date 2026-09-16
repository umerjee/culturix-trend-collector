"""Pure velocity-scoring math — no I/O, easy to unit-test in isolation."""
from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_VELOCITY_THRESHOLD = 500.0  # likes/hour-equivalent; tune per platform norms

# velocity_score is (likes so far) / (hours since posted) -- a LIFETIME AVERAGE
# rate, not a current/instantaneous one. For a post scraped soon after it was
# posted, that average is a reasonable proxy for "how fast is this taking
# off right now." But for a post discovered weeks after posting (common for
# hashtag-search scraping, which surfaces whatever's currently ranked under
# a tag regardless of age), the same formula just reports "total likes /
# total lifetime" -- an old, already-fully-viral video with a high lifetime
# average scores identically to genuine fresh acceleration, even though it's
# stale news the content engine has no fast-reacting reason to be alerted
# about. Real production example (2026-09-16 audit): 4 alerts, all sourced
# from generic fashion-hashtag posts 5-13 days old at scrape time, scoring
# 500-5266 purely from large accumulated like counts. Recency-gating the
# ALERT (not the stored score itself, which stays a valid historical metric)
# restores "velocity" to actually meaning "just started moving," which is
# the only thing worth paging the content engine about.
MAX_POST_AGE_HOURS_FOR_ALERT = 48.0


def hours_since(created_at: datetime, *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max((now - created_at).total_seconds() / 3600.0, 0.0)


def velocity_score(like_count: int, created_at: datetime, *, now: datetime | None = None) -> float:
    """(current_likes) / (hours_since_posted + 1) — a simple recency-weighted
    growth proxy: two posts with equal likes rank by how fast they got there.
    The +1 avoids a divide-by-near-zero spike in a post's first minutes."""
    return like_count / (hours_since(created_at, now=now) + 1.0)


def is_high_velocity(
    score: float,
    threshold: float = DEFAULT_VELOCITY_THRESHOLD,
    *,
    post_age_hours: float | None = None,
    max_age_hours: float = MAX_POST_AGE_HOURS_FOR_ALERT,
) -> bool:
    """post_age_hours is optional (keeps old call sites/tests working) but
    should always be passed in production -- without it this can't tell a
    fresh spike from an old post's high lifetime-average rate."""
    if score < threshold:
        return False
    if post_age_hours is not None and post_age_hours > max_age_hours:
        return False
    return True
