"""Generation cost tracking + budget enforcement for CultureToons.

Every call into KlingOmniProvider, HybridImageProvider, and ElevenLabsProvider
should be recorded here via record_usage() — budget enforcement (check_budget)
is only as complete as this being called consistently at every provider call
site (see app/routers/culturetoons.py and app/services/culturetoon_video.py
for the wired-in call sites).

COST FIGURES — two confidence tiers, do not treat them as equally reliable:
  VERIFIED: image generation's cost_usd is passed through unchanged from
    HybridImageProvider's own MediaResult (Cloudflare's free tier is
    genuinely $0; Qwen-Image's is genuinely None/unknown in this codebase
    today — app/media/image.py's own _COST_USD constant is None, not
    fabricated here).
  PLACEHOLDER: video/voice/registration costs below have no confirmed
    invoiced number anywhere in this codebase. KLING_OMNI_COST_PER_SECOND is
    borrowed from the sibling Kling image-to-video provider's verified rate
    (app/media/video.py, $0.084/sec) as the best available anchor — Kling
    Omni is a different API surface and its actual price has not been
    independently confirmed. ELEVENLABS_COST_PER_CHAR and
    KLING_ELEMENT_REGISTRATION_COST_USD are rough ballparks. Budget
    enforcement built on these numbers is directionally useful, not
    invoiced-accurate, until they're replaced with real figures from each
    provider's billing dashboard.
"""
import logging
import uuid as _uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("culturix.services.culturetoon_usage")

KLING_OMNI_COST_PER_SECOND = Decimal("0.084")          # PLACEHOLDER, see module docstring
ELEVENLABS_COST_PER_CHAR = Decimal("0.00003")           # PLACEHOLDER
KLING_ELEMENT_REGISTRATION_COST_USD = Decimal("0.10")   # PLACEHOLDER

# Budget thresholds — matches the architecture doc's spec-derived example
# (80%/90% warning, 100% hard stop).
WARNING_THRESHOLD_1 = Decimal("0.8")
WARNING_THRESHOLD_2 = Decimal("0.9")
HARD_STOP_THRESHOLD = Decimal("1.0")


def estimate_video_cost(duration_seconds: float) -> Decimal:
    return (KLING_OMNI_COST_PER_SECOND * Decimal(str(duration_seconds))).quantize(Decimal("0.0001"))


def estimate_voice_cost(char_count: int) -> Decimal:
    return (ELEVENLABS_COST_PER_CHAR * char_count).quantize(Decimal("0.0001"))


def record_usage(session, *, user_id, brand_id, generation_type: str, provider: str,
                  toon_id=None, episode_id=None, scene_id=None, shot_id=None, model: Optional[str] = None,
                  input_units: Optional[int] = None, output_units: Optional[int] = None,
                  cost_usd=None) -> None:
    """Adds one GenerationUsage row to `session` — does NOT commit, since
    callers typically already have other writes open in the same
    transaction (e.g. generate_video_for_toon updating the Toon row
    alongside this). Cost is stored as-is, including None (see
    GenerationUsage's docstring on why None must not be treated as 0).
    episode_id/scene_id are set by scene-level generation (see
    app/services/culturetoon_scene.py); shot_id by shot-level generation
    (see app/services/culturetoon_shot.py); toon_id stays the field for the
    original one-shot-per-Toon generation path."""
    from app.models.generation_usage import GenerationUsage
    row = GenerationUsage(
        user_id=_uuid.UUID(str(user_id)), brand_id=_uuid.UUID(str(brand_id)),
        toon_id=_uuid.UUID(str(toon_id)) if toon_id else None,
        episode_id=_uuid.UUID(str(episode_id)) if episode_id else None,
        scene_id=_uuid.UUID(str(scene_id)) if scene_id else None,
        shot_id=_uuid.UUID(str(shot_id)) if shot_id else None,
        provider=provider, model=model, generation_type=generation_type,
        input_units=input_units, output_units=output_units,
        cost_usd=cost_usd,
    )
    session.add(row)


def get_spend(session, brand_id, since: datetime) -> Decimal:
    from sqlalchemy import func
    from app.models.generation_usage import GenerationUsage
    total = session.query(func.coalesce(func.sum(GenerationUsage.cost_usd), 0)).filter(
        GenerationUsage.brand_id == _uuid.UUID(str(brand_id)),
        GenerationUsage.created_at >= since,
    ).scalar()
    return Decimal(str(total or 0))


def check_budget(session, brand) -> dict:
    """Budget check against a CharacterBrand's daily_budget/monthly_budget.
    Returns {"blocked": bool, "reason": str|None, "warning": str|None,
    "daily_spend": Decimal, "monthly_spend": Decimal}.

    A brand with neither budget field set is never blocked or warned —
    budgets are opt-in per brand, not a silent default cap. Because cost_usd
    can be NULL for not-yet-priced generations (see module docstring),
    get_spend's SUM already treats those as excluded (NULL isn't summed by
    SQL SUM), which means spend here is a floor, not a ceiling — actual
    spend may be higher than what's enforceable today."""
    now = datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    daily_spend = get_spend(session, brand.id, day_start) if brand.daily_budget else Decimal("0")
    monthly_spend = get_spend(session, brand.id, month_start) if brand.monthly_budget else Decimal("0")

    result = {
        "blocked": False, "reason": None, "warning": None,
        "daily_spend": daily_spend, "monthly_spend": monthly_spend,
    }

    for label, spend, budget in (
        ("Daily", daily_spend, brand.daily_budget),
        ("Monthly", monthly_spend, brand.monthly_budget),
    ):
        if not budget:
            continue
        budget = Decimal(str(budget))
        ratio = (spend / budget) if budget > 0 else Decimal("0")
        if ratio >= HARD_STOP_THRESHOLD:
            result["blocked"] = True
            result["reason"] = f"{label} budget exceeded (${spend:.2f} of ${budget:.2f})"
            return result
        if ratio >= WARNING_THRESHOLD_1 and not result["warning"]:
            result["warning"] = f"{label} spend at {ratio * 100:.0f}% of budget (${spend:.2f} of ${budget:.2f})"

    return result
