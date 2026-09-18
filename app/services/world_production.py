"""World Feature production — turns a curated, real-source subject
(app/models/curated_item.py: Wikipedia extract or UNESCO site) into a
reviewable script + Toon draft, ready for the paid render step.

Kept out of app/main.py so the whole path (plan -> script -> fact-check ->
persist) is testable and can be dry-run from a script without a web request.

Design rules, each from a failure already documented in
docs/culturix-video-pipeline.md ("Recurring failure patterns"):
- The curated source text is passed INTO the script prompt and the script is
  fact-checked against it — a prompt that only got the title would invent
  dates and figures the DB already has right.
- The suggested duration is visible and overridable BEFORE any generation,
  and a thin source caps the length rather than being padded.
- No on-screen host by default: a factual heritage/history subject is shown
  as real subject footage with narration. A host is opt-in.
"""
import logging
from typing import Optional

from app.collectors.region_codes import region_name

logger = logging.getLogger("culturix.services.world_production")

ALLOWED_DURATIONS = (15, 20, 30, 45, 60)

# Narrative beats per chosen duration when the curator overrides the AI
# suggestion — keeps each shot at or under the renderer's ~12s segment length.
BEATS_FOR_DURATION = {15: 2, 20: 3, 30: 4, 45: 5, 60: 5}

# Below this much source text there are not enough verified facts to fill more
# than a short reveal — padding the rest is exactly how invented detail gets in.
THIN_SOURCE_CHARS = 350
THIN_SOURCE_MAX_SECONDS = 20

_SOURCE_LABELS = {"wikipedia": "Wikipedia", "unesco": "UNESCO World Heritage", "trend": "Trend data"}

_CATEGORY_MAP = {
    "history": "custom", "archaeology": "place", "culture": "custom", "tech": "tech",
    "innovation": "tech", "geopolitical": "custom", "trending": "custom", "humor": "custom",
}


class WorldDraftError(Exception):
    pass


class WorldDraftExists(WorldDraftError):
    """A live (not archived/failed) draft already exists for this item."""


def source_label(item) -> str:
    return _SOURCE_LABELS.get(item.source_type, item.source_type)


def build_source_facts(item) -> str:
    """The verified text the script may draw facts from: the curated summary
    first, then the full source text the item was extracted from."""
    parts = [item.summary.strip()] if item.summary else []
    raw = (item.raw_text or "").strip()
    if raw and raw not in parts:
        parts.append(raw)
    return "\n\n".join(parts)[:5000]


def estimate_render(duration_seconds: int) -> dict:
    """Realistic paid-GPU estimate for a render of this length. Uses the
    measured GPU-seconds per output-second, not a duration-derived guess (see
    culturetoon_selfhosted_video.ltx25_timeout_seconds for why they differ by
    more than an order of magnitude)."""
    from app.services.culturetoon_usage import RENDER_GPU_SECONDS_PER_OUTPUT_SECOND, RUNPOD_GPU_COST_PER_SECOND

    gpu_seconds = float(RENDER_GPU_SECONDS_PER_OUTPUT_SECOND) * duration_seconds
    return {
        "gpu_seconds": round(gpu_seconds),
        "cost_usd": round(gpu_seconds * float(RUNPOD_GPU_COST_PER_SECOND), 2),
    }


def plan_world_video(item) -> dict:
    """Duration/beat recommendation for a subject, with the reasoning and a
    render-cost estimate, so a curator can accept or override it before any
    script is written."""
    from app.services.culturetoon_script import suggest_world_duration

    facts = build_source_facts(item)
    suggestion = suggest_world_duration(item.title, facts[:1200], item.category)
    duration, beats, rationale = suggestion["duration_seconds"], suggestion["beat_count"], suggestion["rationale"]

    thin = len(facts) < THIN_SOURCE_CHARS
    if thin and duration > THIN_SOURCE_MAX_SECONDS:
        duration = THIN_SOURCE_MAX_SECONDS
        beats = min(beats, 3)
        rationale = (f"Source text is short ({len(facts)} characters), so the video is capped at "
                     f"{THIN_SOURCE_MAX_SECONDS}s rather than padded with unverified detail.")
    return {
        "duration_seconds": duration,
        "beat_count": beats,
        "rationale": rationale,
        "allowed_durations": list(ALLOWED_DURATIONS),
        "source_chars": len(facts),
        "thin_source": thin,
        "estimate": {str(d): estimate_render(d) for d in ALLOWED_DURATIONS},
    }


def _world_brand(db):
    from app.models.character_brand import CharacterBrand

    brand = db.query(CharacterBrand).filter_by(name="World").order_by(CharacterBrand.created_at.asc()).first()
    if not brand:
        raise WorldDraftError("Reserved World brand not found (it is seeded at app startup)")
    return brand


def find_live_draft(db, item_id):
    from app.models.toon import Toon

    return (
        db.query(Toon)
        .filter(Toon.curated_item_id == item_id, Toon.status.notin_(["archived", "failed"]))
        .first()
    )


def generate_world_draft(db, item, duration_seconds: Optional[int] = None, beat_count: Optional[int] = None,
                         use_host: bool = False, persist: bool = True) -> dict:
    """Plan -> grounded script -> fact-check (one auto-revision) -> persist as
    an approved ToonScript plus an 'idea' Toon. Does NOT render — the paid GPU
    step stays a separate, explicit action. With persist=False nothing is
    written (dry run). Raises WorldDraftExists on a duplicate live draft."""
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript
    from app.models.trend import Trend
    from app.services.culturetoon_script import (
        generate_world_script, judge_script_comedy, judge_world_grounding, select_thematic_host,
    )

    if persist and find_live_draft(db, item.id):
        raise WorldDraftExists("A World draft already exists for this subject")

    if duration_seconds is not None and duration_seconds not in ALLOWED_DURATIONS:
        raise WorldDraftError(f"duration_seconds must be one of {list(ALLOWED_DURATIONS)}")
    if duration_seconds is None:
        plan = plan_world_video(item)
        duration_seconds = plan["duration_seconds"]
        beat_count = beat_count or plan["beat_count"]
    elif beat_count is None:
        beat_count = BEATS_FOR_DURATION[duration_seconds]
    beat_count = max(1, min(5, int(beat_count)))

    trends = []
    if item.region:
        rows = db.query(Trend).filter(Trend.region == item.region).order_by(Trend.collected_at.desc()).limit(8).all()
        trends = [{"title": r.title, "content": r.content} for r in rows]

    category = _CATEGORY_MAP.get(item.category, "custom")
    host = select_thematic_host(db, category, "informative") if use_host else None
    facts = build_source_facts(item)
    label = source_label(item)

    def _write(avoid=None):
        return generate_world_script(
            region_code=item.region or "", region_label=region_name(item.region),
            subject_text=item.title, subject_category=category, trends=trends,
            culture=None, host_variant=host, tone="informative", num_shots=beat_count,
            target_duration_seconds=duration_seconds, source_facts=facts, source_label=label,
            avoid_claims=avoid,
        )

    result = _write()
    grounding = judge_world_grounding(result, facts)
    if grounding["unsupported_claims"]:
        logger.info("World draft %r had %d unsupported claim(s); revising once", item.title,
                    len(grounding["unsupported_claims"]))
        revised = _write(avoid=grounding["unsupported_claims"])
        revised_grounding = judge_world_grounding(revised, facts)
        if len(revised_grounding["unsupported_claims"]) <= len(grounding["unsupported_claims"]):
            result, grounding = revised, revised_grounding

    judgment = judge_script_comedy(result)
    judgment["grounding"] = grounding
    judgment["duration_plan"] = {"duration_seconds": duration_seconds, "beat_count": beat_count}

    summary = {
        "title": item.title, "duration_seconds": result.get("total_duration_seconds"),
        "requested_duration_seconds": duration_seconds, "shot_count": len(result.get("shots") or []),
        "hook_line": result.get("hook_line"), "grounding": grounding, "judgment": judgment,
        "host": bool(host),
    }
    if not persist:
        return summary

    brand = _world_brand(db)
    script = ToonScript(
        brand_id=brand.id, character_variant_id=host.id if host else None,
        character_variant_ids=[str(host.id)] if host else None,
        hook_line=result.get("hook_line"), tone="informative", shots=result.get("shots"),
        total_duration_seconds=result.get("total_duration_seconds"), comedy_judgment=judgment,
        generation_source="ai", status="approved", is_world_content=True,
        subject_region=item.region, subject_text=item.title, subject_category=category,
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    toon = Toon(
        brand_id=brand.id, character_variant_id=host.id if host else None, script_id=script.id,
        title=item.title, status="idea", is_world_content=True, subject_region=item.region,
        subject_text=item.title, subject_category=category, curated_item_id=item.id,
    )
    db.add(toon)
    db.commit()
    db.refresh(toon)
    summary.update({"toon_id": str(toon.id), "script_id": str(script.id)})
    return summary
