"""Pure velocity-scoring math — no I/O, easy to unit-test in isolation."""
from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_VELOCITY_THRESHOLD = 500.0  # likes/hour-equivalent; tune per platform norms


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


def is_high_velocity(score: float, threshold: float = DEFAULT_VELOCITY_THRESHOLD) -> bool:
    return score >= threshold
