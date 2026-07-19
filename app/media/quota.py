"""Pure plan/quota gating helpers for media generation.

Extracted out of app/main.py's request_generate_media route handler so this
logic is unit-testable without a database or FastAPI request context.
"""

MONTHLY_QUOTA = 50


def plan_blocks_media(plan: str) -> bool:
    """Free plan cannot generate any media; pro/enterprise can."""
    return (plan or "free") == "free"


def quota_exceeded(month_count: int, requested: int, quota: int = MONTHLY_QUOTA) -> bool:
    """True if generating `requested` more items this month would exceed `quota`."""
    return month_count + requested > quota
