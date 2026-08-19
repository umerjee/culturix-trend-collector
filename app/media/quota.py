"""Pure plan/quota gating helpers for generation features — media, and
(see plan_blocks_extra_ideas below) on-demand content ideas beyond the 3
daily proactive ones.

Extracted out of app/main.py's route handlers so this logic is
unit-testable without a database or FastAPI request context.
"""

MONTHLY_QUOTA = 50


def plan_blocks_media(plan: str) -> bool:
    """Free plan cannot generate any media; pro/enterprise can."""
    return (plan or "free") == "free"


def quota_exceeded(month_count: int, requested: int, quota: int = MONTHLY_QUOTA) -> bool:
    """True if generating `requested` more items this month would exceed `quota`."""
    return month_count + requested > quota


def plan_blocks_extra_ideas(plan: str) -> bool:
    """Every plan gets the 3 proactively-generated daily ideas for free —
    that's PROACTIVE_CLUSTER_COUNT in content_strategist.py, unconditional,
    not gated here. Generating MORE via the on-demand "Generate" button for
    any other trend in that day's digest is the pro differentiator —
    unlimited for pro (no monthly cap, unlike media), blocked entirely for
    free. Same shape as plan_blocks_media so both gates read identically
    at their call sites."""
    return (plan or "free") == "free"
