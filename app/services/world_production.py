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
MAX_SCENES = 8

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


# Scene art directions for hostless World videos (None = the default photoreal look).
# Deliberately separate from culturetoons.ART_STYLES, whose prompts describe CHARACTERS
# ("a 2D anime-style character illustration"), which would put a character in a landscape.
WORLD_VISUAL_STYLES = {
    # Wording chosen by a GPU comparison (2026-09-19), not by taste: an 8s D-Day clip with the same
    # action prompt scored ~4.5x the scene motion of the earlier still-looking render, and this
    # description kept a consistent painted look. Positive description only: telling the model what
    # it is NOT ("not a photograph") gave the worst results.
    "illustrated_history": {
        "label": "Illustrated animation (history book)",
        "prompt": "Hand-painted 2D animation in the style of a mid-century history book illustration: "
                  "muted earth palette, visible brush strokes, paper texture, simple stylized figures.",
    },
    "graphic_novel": {
        "label": "Graphic novel animation (inked)",
        "prompt": "Inked graphic-novel animation: bold black linework, limited muted palette, halftone "
                  "shading, dramatic composition, simple stylized figures.",
    },
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
    """Realistic paid-GPU estimate for a render of this length: the measured GPU-seconds per
    output-second times the measured SERVERLESS rate. It used RUNPOD_GPU_COST_PER_SECOND, the old
    $0.50/hr placeholder for a different kind of GPU, and quoted about $0.10 for a video that really
    costs $0.55 to $1.05 (recorded renders, 2026-09), i.e. about a ninth of the real figure. A render
    can cost more than this if a worker has to cold-start or a segment is retried."""
    from app.services.culturetoon_usage import RENDER_GPU_SECONDS_PER_OUTPUT_SECOND, RUNPOD_SERVERLESS_COST_PER_SECOND

    gpu_seconds = float(RENDER_GPU_SECONDS_PER_OUTPUT_SECOND) * duration_seconds
    return {
        "gpu_seconds": round(gpu_seconds),
        "cost_usd": round(gpu_seconds * float(RUNPOD_SERVERLESS_COST_PER_SECOND), 2),
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
        "visual_styles": [{"key": k, "label": v["label"]} for k, v in WORLD_VISUAL_STYLES.items()],
        "source_chars": len(facts),
        "thin_source": thin,
        "estimate": {str(d): estimate_render(d) for d in ALLOWED_DURATIONS},
    }


def _use_reference_people(shots: list, scenes: Optional[list]) -> list:
    """A shot that opens on a real photo shows the photo's real people, so its people mode is
    "reference", not "distant": telling the model they are faceless would fight the photo it is
    conditioned on. Shots without a photo keep the writer's value."""
    if not scenes:
        return shots
    out = []
    for i, shot in enumerate(shots or []):
        shot = dict(shot)
        if i < len(scenes) and scenes[i].get("image_url") and shot.get("people") == "distant":
            shot["people"] = "reference"
        out.append(shot)
    return out


def _world_brand(db):
    from app.models.character_brand import CharacterBrand

    brand = db.query(CharacterBrand).filter_by(name="World").order_by(CharacterBrand.created_at.asc()).first()
    if not brand:
        raise WorldDraftError("Reserved World brand not found (it is seeded at app startup)")
    return brand


MAX_VISUAL_REWRITES = 2
SCRIPTING = "scripting"
SCRIPTING_STALE_MINUTES = 15   # writing takes 1-3 minutes; a longer one was killed by a restart


def scripting_is_stale(toon) -> bool:
    """A draft still marked 'scripting' long after it should have finished: the server restarted while the
    script was being written, so nothing will ever complete it."""
    from datetime import datetime, timedelta
    return (toon.status == SCRIPTING and toon.created_at is not None
            and datetime.utcnow() - toon.created_at > timedelta(minutes=SCRIPTING_STALE_MINUTES))


def find_live_draft(db, item_id):
    from datetime import datetime, timedelta

    from sqlalchemy import and_, or_
    from app.models.toon import Toon

    stale_before = datetime.utcnow() - timedelta(minutes=SCRIPTING_STALE_MINUTES)
    return (
        db.query(Toon)
        .filter(Toon.curated_item_id == item_id, Toon.status.notin_(["archived", "failed"]),
                or_(Toon.status != SCRIPTING, Toon.created_at >= stale_before))
        .first()
    )


def _start_placeholder(db, item, duration_seconds: Optional[int], visual_style: Optional[str]):
    """The draft row, created BEFORE the slow work so it shows in World production the moment the curator
    clicks Generate (greyed, 'under production') instead of appearing minutes later or, if writing fails,
    never. Returns (toon, script)."""
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript

    brand = _world_brand(db)
    category = _CATEGORY_MAP.get(item.category, "custom")
    script = ToonScript(
        brand_id=brand.id, hook_line=None, tone="informative", shots=[], total_duration_seconds=duration_seconds,
        generation_source="ai", status="draft", is_world_content=True, subject_region=item.region,
        subject_text=item.title, subject_category=category, visual_style=visual_style,
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    toon = Toon(brand_id=brand.id, script_id=script.id, title=item.title, status=SCRIPTING, is_world_content=True,
                subject_region=item.region, subject_text=item.title, subject_category=category, curated_item_id=item.id)
    db.add(toon)
    db.commit()
    db.refresh(toon)
    return toon, script


def _fail_placeholder(db, placeholder, exc: Exception) -> None:
    """Mark a draft whose script could not be written as failed, with the reason, so the curator sees it."""
    from app.models.toon import Toon

    try:
        db.rollback()
        toon = db.query(Toon).filter_by(id=placeholder[0].id).first()
        if toon:
            toon.status = "failed"
            toon.generation_error = f"Script writing failed: {exc}"[:2000]
            db.commit()
    except Exception:
        logger.exception("Could not mark draft %s as failed", getattr(placeholder[0], "id", "?"))


def _tag_scene_indexes(shots: list, scenes: Optional[list]) -> None:
    """A shot's scene_index is what the renderer keys its opening-frame photo on; each new scene starts
    a new segment, so every shot renders from its own reference."""
    if scenes:
        for i, shot in enumerate(shots or []):
            if i < len(scenes):
                shot["scene_index"] = i


def _compose_script(db, item, *, duration_seconds: int, beat_count: int, host, scenes: Optional[list],
                    trends: list, category: str, facts: str, label: str, era: Optional[dict] = None,
                    improvements: Optional[list] = None, previous: Optional[dict] = None) -> dict:
    """Write -> visual/motion rules (one rewrite) -> fact-check (one rewrite) -> editorial review.
    With `previous` and `improvements` the writer revises that draft instead of starting fresh.
    Returns {result, grounding, visual_warnings, review}."""
    from app.services.culturetoon_script import (
        check_world_action, check_world_motion, check_world_visuals, generate_world_script,
        judge_world_grounding, normalize_world_people,
    )
    from app.services.world_era import check_world_anachronisms, widen_to_narration
    from app.services.world_review import review_world_script

    def _problems(shots):
        found = (check_world_visuals(shots) + check_world_motion(shots) + check_world_action(shots)
                 + check_world_anachronisms(shots, era))
        if scenes is not None and len(shots or []) != len(scenes):
            found.append(f"Write exactly {len(scenes)} shots, one per scene, in the order given "
                         f"(you wrote {len(shots or [])}).")
        return found

    scene_briefs = [sc["brief"].strip() for sc in scenes] if scenes else None

    def _write(avoid=None, fixes=None):
        return generate_world_script(
            region_code=item.region or "", region_label=region_name(item.region),
            subject_text=item.title, subject_category=category, trends=trends,
            culture=None, host_variant=host, tone="informative", num_shots=beat_count,
            target_duration_seconds=duration_seconds, source_facts=facts, source_label=label,
            avoid_claims=avoid, visual_fixes=fixes, scene_briefs=scene_briefs,
            previous_draft=previous, improvements=improvements, era=era,
        )

    def _settle(script):
        script["shots"], warnings = normalize_world_people(script.get("shots"))
        script["shots"] = _use_reference_people(script["shots"], scenes)
        return script, (warnings + check_world_motion(script.get("shots")) + check_world_action(script.get("shots"))
                        + check_world_anachronisms(script.get("shots"), era))

    result = _write()
    # The renderer says "no people in frame" unless a shot has people="distant", and a visual with a modern
    # object, a map or scenery renders as exactly that. Rewrite against the named problems, up to
    # MAX_VISUAL_REWRITES times while each rewrite is not worse, then normalize. What is still wrong after that
    # is surfaced as a warning, not hidden.
    problems = _problems(result.get("shots"))
    for attempt in range(MAX_VISUAL_REWRITES):
        if not problems:
            break
        logger.info("World draft %r broke the visual rules (%d problem(s)); rewriting (%d/%d)", item.title,
                    len(problems), attempt + 1, MAX_VISUAL_REWRITES)
        revised = _write(fixes=problems)
        revised_problems = _problems(revised.get("shots"))
        if len(revised_problems) > len(problems):
            break
        result, problems = revised, revised_problems
    result, visual_warnings = _settle(result)

    grounding = judge_world_grounding(result, facts)
    if grounding["unsupported_claims"]:
        logger.info("World draft %r had %d unsupported claim(s); revising once", item.title,
                    len(grounding["unsupported_claims"]))
        revised = _write(avoid=grounding["unsupported_claims"], fixes=_problems(result.get("shots")) or None)
        revised, revised_warnings = _settle(revised)
        revised_grounding = judge_world_grounding(revised, facts)
        if len(revised_grounding["unsupported_claims"]) <= len(grounding["unsupported_claims"]):
            result, grounding, visual_warnings = revised, revised_grounding, revised_warnings

    # A script that names a year outside the era (the narration says "in 27 BC") widens the era to reach it.
    era = widen_to_narration(era, result.get("shots"))
    review = review_world_script(result, item.title, duration_seconds, facts, grounding, era)
    return {"result": result, "grounding": grounding, "visual_warnings": visual_warnings, "review": review, "era": era}


def _is_better(new: dict, old: dict) -> bool:
    """A revision replaces a draft only if it scores higher without adding unsupported claims."""
    new_score, old_score = new["review"]["score"], old["review"]["score"]
    if new_score is None:
        return False
    if len(new["grounding"]["unsupported_claims"]) > len(old["grounding"]["unsupported_claims"]):
        return False
    return old_score is None or new_score > old_score


def _build_judgment(composed: dict, duration_seconds: int, beat_count: int, scenes: Optional[list],
                    previous_judgment: Optional[dict] = None) -> dict:
    judgment = dict(composed["review"])
    judgment["era"] = composed.get("era")
    judgment["grounding"] = composed["grounding"]
    judgment["duration_plan"] = {"duration_seconds": duration_seconds, "beat_count": beat_count}
    if scenes:
        judgment["references"] = [{"scene": i, "url": sc.get("image_url"), "credit": sc.get("credit"),
                                   "source_page": sc.get("source_page")} for i, sc in enumerate(scenes)]
        judgment["scene_briefs"] = [sc["brief"] for sc in scenes]
    elif previous_judgment:
        for key in ("references", "scene_briefs"):
            if previous_judgment.get(key):
                judgment[key] = previous_judgment[key]
    if composed["visual_warnings"]:
        judgment["visual_warnings"] = composed["visual_warnings"]
    return judgment


def generate_world_draft(db, item, duration_seconds: Optional[int] = None, beat_count: Optional[int] = None,
                         use_host: bool = False, persist: bool = True,
                         visual_style: Optional[str] = None, scenes: Optional[list] = None,
                         era_text: Optional[str] = None) -> dict:
    """Plan -> grounded script -> fact-check (one auto-revision) -> editorial review (one auto-improvement
    if it does not pass) -> persist as an approved ToonScript plus an 'idea' Toon. Does NOT render:
    the paid GPU step stays a separate, explicit action. With persist=False nothing is written (dry
    run). Raises WorldDraftExists on a duplicate live draft.

    The draft row exists from the start with status 'scripting' (see _start_placeholder) and becomes 'idea'
    when the script is done, or 'failed' with the reason if writing raises."""
    if persist and find_live_draft(db, item.id):
        raise WorldDraftExists("A World draft already exists for this subject")
    placeholder = _start_placeholder(db, item, duration_seconds, visual_style) if persist else None
    try:
        return _generate_world_draft(db, item, duration_seconds, beat_count, use_host, persist, visual_style,
                                     scenes, era_text, placeholder)
    except Exception as exc:
        if placeholder:
            _fail_placeholder(db, placeholder, exc)
        raise


def _generate_world_draft(db, item, duration_seconds, beat_count, use_host, persist, visual_style, scenes,
                          era_text, placeholder) -> dict:
    from app.models.trend import Trend
    from app.services.culturetoon_script import select_thematic_host
    from app.services.world_era import determine_world_era, era_from_text
    from app.services.world_review import improvement_notes

    if visual_style is not None and visual_style not in WORLD_VISUAL_STYLES:
        raise WorldDraftError(f"visual_style must be one of {sorted(WORLD_VISUAL_STYLES)} or omitted")
    if scenes is not None:
        # One shot per scene, each opening on that scene's reference photo (see world_references).
        if not 1 <= len(scenes) <= MAX_SCENES or any(not (sc.get("brief") or "").strip() for sc in scenes):
            raise WorldDraftError(f"scenes must be 1-{MAX_SCENES} items, each with a brief")
        beat_count = len(scenes)
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
    # When the video is set. The curator's own words win; otherwise it is decided once here, so the writer,
    # the anachronism check, the reviewer and the renderer all use the same period.
    try:
        era = era_from_text(era_text) if (era_text or "").strip() else determine_world_era(item.title, facts)
    except ValueError as exc:
        raise WorldDraftError(str(exc)) from exc
    common = dict(duration_seconds=duration_seconds, beat_count=beat_count, host=host, scenes=scenes,
                  trends=trends, category=category, facts=facts, label=label, era=era)

    composed = _compose_script(db, item, **common)
    review = composed["review"]
    if review["passes_bar"] is False and review["suggestions"]:
        # The same loop the curator gets from "Improve with AI", applied once automatically: the draft
        # they first see is already the better of the two.
        logger.info("World draft %r scored %s (below the bar); improving once", item.title, review["score"])
        better = _compose_script(db, item, improvements=improvement_notes(review), previous=composed["result"], **common)
        if _is_better(better, composed):
            better["review"]["auto_improved"] = True
            better["review"]["first_score"] = review["score"]
            composed = better

    result, grounding = composed["result"], composed["grounding"]
    judgment = _build_judgment(composed, duration_seconds, beat_count, scenes)
    summary = {
        "title": item.title, "duration_seconds": result.get("total_duration_seconds"),
        "requested_duration_seconds": duration_seconds, "shot_count": len(result.get("shots") or []),
        "hook_line": result.get("hook_line"), "grounding": grounding, "judgment": judgment,
        "host": bool(host), "visual_style": visual_style, "scenes": len(scenes) if scenes else 0,
        "shots": result.get("shots"),
    }
    if not persist:
        return summary

    brand = _world_brand(db)
    scene_backgrounds = None
    if scenes:
        from app.models.toon_background import ToonBackground
        _tag_scene_indexes(result["shots"], scenes)
        scene_backgrounds = []
        for i, sc in enumerate(scenes):
            if sc.get("image_url"):
                bg = ToonBackground(brand_id=brand.id, name=(sc.get("name") or sc["brief"])[:120],
                                    image_url=sc["image_url"], description=sc["brief"],
                                    country=region_name(item.region) if item.region else None,
                                    tags="world,reference")
                db.add(bg)
                db.commit()
                db.refresh(bg)
                scene_backgrounds.append({"scene_index": i, "background_id": str(bg.id)})
    toon, script = placeholder
    db.refresh(toon)
    if toon.status != SCRIPTING:
        # Archived (or otherwise changed) while the script was being written: do not reopen it.
        return summary
    script.character_variant_id = host.id if host else None
    script.character_variant_ids = [str(host.id)] if host else None
    script.hook_line = result.get("hook_line")
    script.shots = result.get("shots")
    script.total_duration_seconds = result.get("total_duration_seconds")
    script.comedy_judgment = judgment
    script.status = "approved"
    script.scene_backgrounds = scene_backgrounds
    toon.character_variant_id = host.id if host else None
    toon.status = "idea"
    db.commit()
    summary.update({"toon_id": str(toon.id), "script_id": str(script.id)})
    return summary


def ensure_script_era(db, toon, script) -> Optional[dict]:
    """The era a World script is set in, working it out and saving it if the draft predates periods. Called
    before a preview or a render builds any prompt: without an era a render of ancient Rome gets the model's
    default, the present day (jeeps at the huts). Best effort: None if it cannot be decided, and a failure
    here must never block a render."""
    judgment = script.comedy_judgment if isinstance(script.comedy_judgment, dict) else {}
    if judgment.get("era"):
        return judgment["era"]
    try:
        from app.models.curated_item import CuratedItem
        from app.services.world_era import determine_world_era, widen_to_narration

        item = db.query(CuratedItem).filter_by(id=toon.curated_item_id).first() if toon.curated_item_id else None
        if not item:
            return None
        era = widen_to_narration(determine_world_era(item.title, build_source_facts(item)), script.shots)
        if era:
            script.comedy_judgment = {**judgment, "era": era}
            db.commit()
        return era
    except Exception:
        logger.warning("Could not work out the era for draft %s", getattr(toon, "id", "?"), exc_info=True)
        db.rollback()
        return None


EDITABLE_STATUSES = ("idea", "failed")


def _editable_draft(db, toon):
    """(script, curated item) for a draft whose script can still change. Once a video exists the script
    describes that video, so editing it would make the page lie about what was rendered."""
    from app.models.curated_item import CuratedItem
    from app.models.toon_script import ToonScript

    if toon.status == SCRIPTING:
        raise WorldDraftError("The script is still being written")
    if toon.status not in EDITABLE_STATUSES:
        raise WorldDraftError("A script can only be scored or improved before its video is rendered")
    script = db.query(ToonScript).filter_by(id=toon.script_id).first()
    item = db.query(CuratedItem).filter_by(id=toon.curated_item_id).first() if toon.curated_item_id else None
    if not script or not item or not script.shots:
        raise WorldDraftError("This draft has no script yet, or no source subject to review it against")
    return script, item


def _scenes_for_script(db, script) -> Optional[list]:
    """The scene list a draft was written against, rebuilt from its stored reference-photo locations so a
    revision keeps one shot per scene and each shot's photo."""
    if not script.scene_backgrounds:
        return None
    import uuid

    from app.models.toon_background import ToonBackground

    by_index = {e["scene_index"]: e["background_id"] for e in script.scene_backgrounds if e.get("background_id")}
    if not by_index:
        return None
    ids = [uuid.UUID(str(v)) for v in by_index.values()]
    rows = {str(r.id): r for r in db.query(ToonBackground).filter(ToonBackground.id.in_(ids)).all()}
    saved_briefs = (script.comedy_judgment or {}).get("scene_briefs") or []
    scenes = []
    for i, shot in enumerate(script.shots or []):
        bg = rows.get(by_index.get(i))
        brief = (saved_briefs[i] if i < len(saved_briefs) else None) or (bg.description if bg else None) \
            or shot.get("subject_visual") or ""
        scenes.append({"brief": brief, "image_url": bg.image_url if bg else None, "name": bg.name if bg else None})
    return scenes


def review_world_draft(db, toon) -> dict:
    """Score a draft's stored script (for drafts written before scoring existed, or after a manual edit)
    and save the review. One LLM call, no rendering."""
    from app.services.culturetoon_script import judge_world_grounding
    from app.services.world_review import review_world_script

    script, item = _editable_draft(db, toon)
    facts = build_source_facts(item)
    stored = {"hook_line": script.hook_line, "shots": script.shots}
    previous = script.comedy_judgment or {}
    grounding = previous.get("grounding") or judge_world_grounding(stored, facts)
    era = previous.get("era")
    if not era:
        # A draft written before periods existed: decide it now, so it is scored (and rendered) against one.
        from app.services.world_era import determine_world_era, widen_to_narration
        era = widen_to_narration(determine_world_era(item.title, facts), script.shots)
    review = review_world_script(stored, item.title, script.total_duration_seconds, facts, grounding, era)
    judgment = dict(previous)
    judgment.update(review)
    judgment["grounding"] = grounding
    script.comedy_judgment = judgment
    db.commit()
    return review


def improve_world_draft(db, toon, note: Optional[str] = None) -> dict:
    """Revise a draft's script with the reviewer's suggestions (and an optional note from the curator),
    then re-check and re-score it. Replaces the stored script only if the revision scores higher without
    adding unsupported claims; otherwise the draft is left as it was. Returns {improved, score_before,
    score_after, message}."""
    from app.models.trend import Trend
    from app.services.culturetoon_script import select_thematic_host
    from app.services.world_review import improvement_notes

    script, item = _editable_draft(db, toon)
    ensure_script_era(db, toon, script)
    judgment = script.comedy_judgment or {}
    if not judgment.get("suggestions") and not (note or "").strip():
        review_world_draft(db, toon)
        judgment = script.comedy_judgment or {}
    notes = improvement_notes(judgment, note)
    if not notes:
        return {"improved": False, "score_before": judgment.get("score"), "score_after": judgment.get("score"),
                "message": "The reviewer has no suggestions for this script. Add a note to ask for a specific change."}

    scenes = _scenes_for_script(db, script)
    plan = judgment.get("duration_plan") or {}
    duration_seconds = plan.get("duration_seconds") or script.total_duration_seconds or 30
    beat_count = len(scenes) if scenes else plan.get("beat_count") or len(script.shots or []) or 3
    trends = []
    if item.region:
        rows = db.query(Trend).filter(Trend.region == item.region).order_by(Trend.collected_at.desc()).limit(8).all()
        trends = [{"title": r.title, "content": r.content} for r in rows]
    category = _CATEGORY_MAP.get(item.category, "custom")
    host = None
    if script.character_variant_id:
        from app.models.character_variant import CharacterVariant
        host = db.query(CharacterVariant).filter_by(id=script.character_variant_id).first()
    facts = build_source_facts(item)
    common = dict(duration_seconds=duration_seconds, beat_count=beat_count, host=host, scenes=scenes,
                  trends=trends, category=category, facts=facts, label=source_label(item), era=judgment.get("era"))

    current = {"hook_line": script.hook_line, "shots": script.shots}
    old = {"result": current, "grounding": judgment.get("grounding") or {"grounded": None, "unsupported_claims": []},
           "review": {"score": judgment.get("score")}}
    better = _compose_script(db, item, improvements=notes, previous=current, **common)
    if not _is_better(better, old):
        return {"improved": False, "score_before": judgment.get("score"), "score_after": better["review"]["score"],
                "message": "The rewrite did not score higher, so the current script was kept."}

    result = better["result"]
    _tag_scene_indexes(result["shots"], scenes)
    new_judgment = _build_judgment(better, duration_seconds, beat_count, scenes, previous_judgment=judgment)
    new_judgment["first_score"] = judgment.get("score")
    script.hook_line = result.get("hook_line")
    script.shots = result.get("shots")
    script.total_duration_seconds = result.get("total_duration_seconds")
    script.comedy_judgment = new_judgment
    db.commit()
    return {"improved": True, "score_before": judgment.get("score"), "score_after": better["review"]["score"],
            "message": "Script improved."}


def preview_world_render(db, toon) -> dict:
    """Exactly what a render of this draft would send, before any GPU is spent: the narration (voice,
    timing), and per video segment the opening frame, the full text prompt and the negative prompt. Built
    by the same functions the renderer calls (culturetoon_selfhosted_video.plan_ltx25_segments and
    load_render_context), so it cannot drift from a real render."""
    from app.models.toon_script import ToonScript
    from app.services import culturetoon_selfhosted_video as video
    from app.services import world_narration

    script = db.query(ToonScript).filter_by(id=toon.script_id).first()
    if not script:
        raise WorldDraftError("This draft has no script")
    try:
        variants, background, scene_backgrounds = video.load_render_context(db, toon, script)
    except ValueError as exc:
        raise WorldDraftError(str(exc)) from exc

    duration = script.total_duration_seconds or sum(s.get("duration_seconds", 0) for s in (script.shots or [])) or 5
    render_script = script
    narration = None
    if script.is_world_content and not variants:
        try:
            plan = world_narration.prepare_narration_cached(script.shots or [], language="en")
            render_script = plan.render_script(script)
            duration = int(plan.total_seconds) or duration
            narration = {
                "voice": plan.voice, "language": plan.language, "error": None,
                "lines": [{"shot": ln.shot_index + 1, "text": ln.text, "starts_at": round(ln.start, 1),
                           "speech_seconds": round(ln.duration, 1)} for ln in plan.lines],
                "shot_seconds": [s["duration_seconds"] for s in plan.shots],
                "mix": {"ambient_volume": world_narration.AMBIENT_GAIN, "loudness_lufs": world_narration.TARGET_LUFS},
            }
        except world_narration.NarrationError as exc:
            narration = {"voice": None, "language": "en", "lines": [], "shot_seconds": [], "mix": None,
                         "error": f"The render would stop before using the GPU: {exc}"}

    segments = video.plan_ltx25_segments(render_script, variants, background, scene_backgrounds)
    look = WORLD_VISUAL_STYLES.get(script.visual_style or "", {}).get("label") or "Photoreal (default)"
    return {
        "toon_id": str(toon.id), "title": toon.title, "duration_seconds": duration, "look": look,
        "estimate": estimate_render(duration), "narration": narration, "segments": segments,
    }
