"""Analytics feedback loop for CultureToons — see
docs/culturix-comedy-architecture.md §3.11 and §7 Phase 8.

Deliberately computed live at script-generation time, not via a scheduled
aggregation job the doc originally sketched — the join here (ToonPost ->
Toon -> ToonScript, one brand at a time) is small and cheap at current
volume, so a scheduled pre-aggregation + cache would be solving a
performance problem that doesn't exist yet, at the cost of staleness and
scheduler complexity. Revisit only if this measurably shows up as a
bottleneck — matches this codebase's own "don't over-engineer before
proving the need" principle."""
import logging
from typing import Optional

logger = logging.getLogger("culturix.services.culturetoon_analytics")


def _duration_bucket(seconds: Optional[int]) -> str:
    if not seconds:
        return "unknown"
    if seconds <= 8:
        return "short (<=8s)"
    if seconds <= 15:
        return "medium (9-15s)"
    return "long (>15s)"


def compute_performance_summary(session, brand_id) -> list:
    """Groups tracked ToonPost performance by (cast, tone, duration bucket).
    Returns a list of {"variant_ids": set[str], "tone": str,
    "duration_bucket": str, "post_count": int, "avg_views": float,
    "avg_engagement_rate": float} — engagement_rate = (likes+comments+
    shares)/views per post, averaged, 0 when views is 0/None."""
    from app.models.toon_post import ToonPost
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript
    import uuid as _uuid

    rows = (
        session.query(ToonPost, Toon, ToonScript)
        .join(Toon, ToonPost.toon_id == Toon.id)
        .join(ToonScript, Toon.script_id == ToonScript.id)
        .filter(ToonPost.brand_id == _uuid.UUID(str(brand_id)), ToonPost.status == "tracked")
        .all()
    )

    buckets: dict = {}
    for post, toon, script in rows:
        cast_ids = script.character_variant_ids or ([str(toon.character_variant_id)] if toon.character_variant_id else [])
        key = (frozenset(cast_ids), script.tone or "unknown", _duration_bucket(script.total_duration_seconds))
        views = post.latest_views or 0
        engagement = ((post.latest_likes or 0) + (post.latest_comments or 0) + (post.latest_shares or 0)) / views if views else 0.0
        buckets.setdefault(key, []).append((views, engagement))

    summary = []
    for (variant_ids, tone, bucket), values in buckets.items():
        views_list = [v for v, _ in values]
        engagement_list = [e for _, e in values]
        summary.append({
            "variant_ids": variant_ids, "tone": tone, "duration_bucket": bucket,
            "post_count": len(values),
            "avg_views": sum(views_list) / len(views_list),
            "avg_engagement_rate": sum(engagement_list) / len(engagement_list),
        })
    return summary


def get_cast_performance_context(session, brand_id, variant_ids: list, top_n: int = 2) -> str:
    """Short text summary of how this specific cast (or an overlapping one)
    has performed historically, for injection into the script-suggestion
    prompt — the actual "feedback loop" (§3.11). Returns "" if there's no
    tracked post data yet for this brand (a brand new to publishing has
    nothing to learn from, and that must not read as an error)."""
    try:
        summary = compute_performance_summary(session, brand_id)
    except Exception:
        logger.warning("Performance summary computation failed, continuing without it", exc_info=True)
        return ""
    if not summary:
        return ""

    target = {str(v) for v in variant_ids}
    relevant = [row for row in summary if row["variant_ids"] & target]
    if not relevant:
        return ""
    relevant.sort(key=lambda r: (r["avg_engagement_rate"], r["post_count"]), reverse=True)
    top = relevant[:top_n]

    lines = [
        f"- {row['tone']} tone, {row['duration_bucket']}: {row['post_count']} post(s), "
        f"avg {row['avg_views']:.0f} views, {row['avg_engagement_rate']:.1%} engagement"
        for row in top
    ]
    return (
        "\nPast performance for this cast (from published posts — use this to inform tone/pacing choices, "
        "don't force it into the scene itself):\n" + "\n".join(lines) + "\n"
    )
