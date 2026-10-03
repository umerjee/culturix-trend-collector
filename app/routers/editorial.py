"""Admin endpoints for the trend-to-culture editorial workflow (see app/services/editorial.py).

Mounted in app/main.py behind require_admin_secret, so only the superadmin console's server-side
proxies can reach it. The proxies add `reviewer` (the signed-in admin's email) and, for script
generation, `user_id` (the admin's own Supabase id, which owns the CultureToons brands).

LLM work never runs inside an open DB session: a connection held across a multi-minute model call
is the stale-connection failure documented in app/db.py::resilient_commit.
"""
import logging
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.services import editorial as ed

logger = logging.getLogger("culturix.routers.editorial")
router = APIRouter(prefix="/admin/editorial", tags=["editorial"])

OPEN_STATUSES = ("candidate", "scripted", "approved", "published")
_METRIC_FIELDS = ("views", "likes", "comments", "shares")
_EXTRA_METRIC_FIELDS = ("saves", "follows", "avg_watch_seconds", "completion_rate")


def _uuid_or_404(value: str, what: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail=f"{what} not found")


def _get_candidate(session, candidate_id: str):
    from app.models.editorial_candidate import EditorialCandidate
    row = session.query(EditorialCandidate).filter_by(id=_uuid_or_404(candidate_id, "Candidate")).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return row


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def serialize_candidate(c, script=None) -> dict:
    from app.services.world_production import _SOURCE_LABELS
    out = {
        "id": str(c.id), "status": c.status, "region": c.region, "continent": c.continent,
        "trend": {"type": c.trend_type, "id": c.trend_id, "title": c.trend_title, "summary": c.trend_summary,
                  "platforms": c.trend_platforms or [], "momentum": c.trend_momentum},
        "source": {"curated_item_id": str(c.curated_item_id), "type": c.source_type,
                   "label": _SOURCE_LABELS.get(c.source_type, c.source_type), "title": c.source_title,
                   "url": c.source_url, "excerpt": c.source_excerpt},
        "rank_score": c.rank_score, "rank_factors": c.rank_factors or [], "rank_weights_version": c.rank_weights_version,
        "safety": {"status": c.safety_status, "exclusions": c.safety_flags or [], "review": c.safety_review_flags or [],
                   "checklist": c.safety_checklist, "note": c.safety_note, "reviewed_by": c.safety_reviewed_by,
                   "reviewed_at": _iso(c.safety_reviewed_at)},
        "brand_id": str(c.brand_id) if c.brand_id else None,
        "script_id": str(c.script_id) if c.script_id else None,
        "grounding": c.grounding, "grounding_status": c.grounding_status,
        "language": c.language, "format": c.format,
        "toon_id": str(c.toon_id) if c.toon_id else None,
        "approved_by": c.approved_by, "approved_at": _iso(c.approved_at),
        "created_at": _iso(c.created_at), "updated_at": _iso(c.updated_at),
    }
    if script is not None:
        out["script"] = {"hook_line": script.hook_line, "tone": script.tone, "shots": script.shots or [],
                         "total_duration_seconds": script.total_duration_seconds,
                         "character_variant_ids": list(script.character_variant_ids or []),
                         "comedy_score": (script.comedy_judgment or {}).get("comedy_score"),
                         "changed_since_approval": bool(c.approved_script_fingerprint)
                         and c.approved_script_fingerprint != ed.script_fingerprint(script)}
    return out


@router.get("/candidates")
def list_candidates(status: Optional[str] = None, limit: int = 100):
    """Open candidates balanced across continents (round-robin, rank order within each), plus the
    coverage counts and any target continent with no candidates at all."""
    from app.db import SessionLocal
    from app.models.editorial_candidate import EditorialCandidate
    from app.models.toon_script import ToonScript

    limit = max(1, min(limit, 300))
    session = SessionLocal()
    try:
        q = session.query(EditorialCandidate)
        q = q.filter(EditorialCandidate.status == status) if status else q.filter(EditorialCandidate.status.in_(OPEN_STATUSES + ("blocked",)))
        rows = q.order_by(EditorialCandidate.created_at.desc()).limit(500).all()
        script_ids = [r.script_id for r in rows if r.script_id]
        scripts = {s.id: s for s in session.query(ToonScript).filter(ToonScript.id.in_(script_ids)).all()} if script_ids else {}
        items = [serialize_candidate(r, scripts.get(r.script_id)) for r in rows]
        open_items = [i for i in items if i["status"] != "blocked"]
        blocked = [i for i in items if i["status"] == "blocked"]
        return {"candidates": ed.balance_slate(open_items)[:limit], "blocked": blocked[:50],
                "coverage": ed.coverage_summary(open_items), "formats": ed.EDITORIAL_FORMATS,
                "languages": ed.LANGUAGES, "safety_checklist": ed.SAFETY_CHECKLIST,
                "rank_weights": ed.RANK_WEIGHTS, "rank_weights_version": ed.RANK_WEIGHTS_VERSION}
    finally:
        session.close()


@router.post("/candidates/refresh")
def refresh_candidates(body: Optional[dict] = None):
    """Builds new candidates from the last `days` of trends and the curated source library.
    `brand_id` is optional and only feeds the cast-fit factor."""
    from app.db import SessionLocal
    body = body or {}
    try:
        days = int(body.get("days") or ed.TREND_LOOKBACK_DAYS)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="days must be an integer")
    if not 1 <= days <= 30:
        raise HTTPException(status_code=400, detail="days must be between 1 and 30")

    session = SessionLocal()
    try:
        cast_regions = None
        if body.get("brand_id"):
            cast_regions = ed.cast_home_regions(session, _uuid_or_404(body["brand_id"], "Brand"))
        result = ed.build_candidates(session, cast_regions=cast_regions, days=days)
        session.commit()
        created = result["created"]
        return {"created": len(created), "blocked": sum(1 for c in created if c.status == "blocked"),
                "rescreened_blocked": len(result["rescreened_blocked"]),
                "skipped_regions": result["skipped_regions"],
                "coverage": ed.coverage_summary([{"continent": c.continent} for c in created if c.status != "blocked"])}
    finally:
        session.close()


@router.post("/candidates/{candidate_id}/safety")
def review_safety(candidate_id: str, body: dict):
    """decision: clear | block | reject. Clearing needs every SAFETY_CHECKLIST answer true and is
    impossible for a candidate with an automatic exclusion. Block is a safety decision; reject is
    an editorial one (not a fit). Both are terminal."""
    from app.db import SessionLocal
    decision = body.get("decision")
    if decision not in ("clear", "block", "reject"):
        raise HTTPException(status_code=400, detail="decision must be clear, block or reject")
    note = (body.get("note") or "").strip() or None
    session = SessionLocal()
    try:
        c = _get_candidate(session, candidate_id)
        if c.status in ("blocked", "rejected"):
            raise HTTPException(status_code=409, detail=f"Candidate is already {c.status}")
        if decision == "clear":
            if c.safety_flags:
                raise HTTPException(status_code=409, detail="This candidate hit an automatic safety exclusion and cannot be cleared")
            checklist = body.get("checklist") or {}
            missing = [k for k in ed.SAFETY_CHECKLIST if checklist.get(k) is not True]
            if missing:
                raise HTTPException(status_code=400, detail={"message": "Every checklist item must be confirmed", "missing": missing})
            c.safety_status, c.safety_checklist = "cleared", {k: True for k in ed.SAFETY_CHECKLIST}
        elif decision == "block":
            if not note:
                raise HTTPException(status_code=400, detail="A note is required to block a candidate")
            c.safety_status, c.status = "blocked", "blocked"
        else:
            c.status = "rejected"
        c.safety_note = note or c.safety_note
        c.safety_reviewed_by = body.get("reviewer")
        c.safety_reviewed_at = datetime.utcnow()
        session.commit()
        session.refresh(c)
        return serialize_candidate(c)
    finally:
        session.close()


@router.post("/candidates/{candidate_id}/script")
def generate_candidate_script(candidate_id: str, body: dict):
    """Writes a comedy script for the candidate with the brand's own cast, using the existing
    cast-aware writer, then fact-checks it against the source excerpt only."""
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    from app.routers.culturetoons import (
        _get_brand_owned, _resolve_cast, _extract_cast_ids, _validate_script_generation_params,
        _gather_script_generation_context,
    )
    from app.services.culturetoon_script import (
        generate_toon_script_from_idea, judge_script_comedy, ToonScriptGenerationError, TONE_OPTIONS,
    )

    user_id, brand_id = body.get("user_id"), body.get("brand_id")
    fmt, language, tone = body.get("format"), body.get("language") or "en", body.get("tone") or "funny"
    if not user_id or not brand_id:
        raise HTTPException(status_code=400, detail="user_id and brand_id are required")
    if fmt not in ed.EDITORIAL_FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {list(ed.EDITORIAL_FORMATS)}")
    if language not in ed.LANGUAGES:
        raise HTTPException(status_code=400, detail=f"language must be one of {list(ed.LANGUAGES)}")
    if tone not in TONE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"tone must be one of {TONE_OPTIONS}")
    if not _extract_cast_ids(body):
        raise HTTPException(status_code=400, detail="Pick at least one character for the cast")
    num_shots, target_duration_seconds = _validate_script_generation_params(body)

    # Phase 1: validate and gather context, then release the connection before any model call.
    session = SessionLocal()
    try:
        c = _get_candidate(session, candidate_id)
        if c.status not in ("candidate", "scripted"):
            raise HTTPException(status_code=409, detail=f"A {c.status} candidate cannot be re-scripted")
        _get_brand_owned(session, brand_id, user_id)
        variants = _resolve_cast(session, body, brand_id, user_id)
        brief = ed.build_script_brief(c, fmt, language)
        personalities, relationships, memories, cultures, performance = _gather_script_generation_context(
            session, brand_id, variants, c.trend_title)
        excerpt, region, trend_id, trend_type = c.source_excerpt, c.region, c.trend_id, c.trend_type
        cast_ids = [str(v.id) for v in variants]
        primary_id = variants[0].id
        session.expunge_all()
    finally:
        session.close()

    # Phase 2: model calls, no session held.
    try:
        result = generate_toon_script_from_idea(
            brief, variants, tone=tone, num_shots=num_shots, target_duration_seconds=target_duration_seconds,
            character_personalities=personalities, relationships=relationships, memories=memories,
            cultures=cultures, performance_context=performance)
    except ToonScriptGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"Script generation failed: {exc}")
    result, grounding = ed.ground_script(result, excerpt)
    craft = judge_script_comedy(result)

    # Phase 3: persist with a fresh session.
    session = SessionLocal()
    try:
        c = _get_candidate(session, candidate_id)
        script = ToonScript(
            brand_id=_uuid.UUID(brand_id), character_variant_id=primary_id, character_variant_ids=cast_ids,
            source_type="idea", idea_text=brief, hook_line=result.get("hook_line"), tone=result.get("tone") or tone,
            shots=result.get("shots"), total_duration_seconds=result.get("total_duration_seconds"),
            comedy_judgment={**(craft or {}), "grounding": grounding, "editorial_candidate_id": str(c.id)},
            subject_region=region, trend_source_id=trend_id, trend_source_type=trend_type,
            generation_source="ai", status="draft",
        )
        session.add(script)
        session.flush()
        c.brand_id, c.script_id = _uuid.UUID(brand_id), script.id
        c.grounding, c.grounding_status = grounding, ed.grounding_status(grounding)
        c.format, c.language, c.status = fmt, language, "scripted"
        session.commit()
        session.refresh(c)
        return serialize_candidate(c, script)
    finally:
        session.close()


@router.post("/candidates/{candidate_id}/grounding")
def recheck_grounding(candidate_id: str):
    """Re-runs the fact-check on the script as it is NOW (e.g. after an edit in the Comedy studio).
    Does not rewrite anything; it only reports."""
    from app.db import SessionLocal
    from app.models.toon_script import ToonScript
    from app.services.culturetoon_script import judge_world_grounding

    session = SessionLocal()
    try:
        c = _get_candidate(session, candidate_id)
        script = session.query(ToonScript).filter_by(id=c.script_id).first() if c.script_id else None
        if script is None:
            raise HTTPException(status_code=409, detail="Generate a script first")
        current = {"hook_line": script.hook_line, "shots": script.shots or []}
        excerpt = c.source_excerpt
    finally:
        session.close()

    grounding = judge_world_grounding(current, excerpt)
    grounding["claims"] = ed.link_claims_to_source(current, excerpt, grounding.get("unsupported_claims") or [])

    session = SessionLocal()
    try:
        c = _get_candidate(session, candidate_id)
        script = session.query(ToonScript).filter_by(id=c.script_id).first()
        c.grounding, c.grounding_status = grounding, ed.grounding_status(grounding)
        script.comedy_judgment = {**(script.comedy_judgment or {}), "grounding": grounding}
        session.commit()
        session.refresh(c)
        return serialize_candidate(c, script)
    finally:
        session.close()


@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(candidate_id: str, body: Optional[dict] = None):
    """The render/publish gate opens here and only here: safety cleared, claims grounded, a script
    exists. Creates the Toon (rendered from the Comedy studio as usual) and remembers the script's
    fingerprint so a later edit closes the gate again."""
    from app.db import SessionLocal
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript

    body = body or {}
    session = SessionLocal()
    try:
        c = _get_candidate(session, candidate_id)
        if c.status not in ("scripted", "approved"):
            raise HTTPException(status_code=409, detail=f"A {c.status} candidate cannot be approved")
        if c.safety_status != "cleared":
            raise HTTPException(status_code=409, detail="Clear the safety review first")
        if c.grounding_status != "grounded":
            raise HTTPException(status_code=409, detail="Every factual claim must be grounded in the source first")
        script = session.query(ToonScript).filter_by(id=c.script_id).first() if c.script_id else None
        if script is None or not script.shots:
            raise HTTPException(status_code=409, detail="Generate a script first")
        if c.toon_id is None:
            toon = Toon(brand_id=script.brand_id, character_variant_id=script.character_variant_id,
                        script_id=script.id, title=(script.hook_line or c.trend_title)[:255], status="idea",
                        subject_region=c.region)
            session.add(toon)
            session.flush()
            c.toon_id = toon.id
        script.status = "approved"
        c.status = "approved" if c.status != "published" else c.status
        c.approved_script_fingerprint = ed.script_fingerprint(script)
        c.approved_by, c.approved_at = body.get("reviewer"), datetime.utcnow()
        session.commit()
        session.refresh(c)
        return serialize_candidate(c, script)
    finally:
        session.close()


def _validated_metrics(body: dict, require_core: bool) -> tuple:
    core, extra = {}, {}
    for field in _METRIC_FIELDS:
        value = body.get(field)
        if value is None or value == "":
            if require_core:
                raise HTTPException(status_code=400, detail=f"{field} is required (use 0 if none)")
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise HTTPException(status_code=400, detail=f"{field} must be a whole number of 0 or more")
        core[field] = value
    for field in _EXTRA_METRIC_FIELDS:
        value = body.get(field)
        if value is None or value == "":
            continue
        if field == "completion_rate":
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise HTTPException(status_code=400, detail="completion_rate must be between 0 and 1")
        elif not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise HTTPException(status_code=400, detail=f"{field} must be 0 or more")
        extra[field] = value
    return core, extra


@router.post("/candidates/{candidate_id}/posts")
def record_post(candidate_id: str, body: dict):
    """Records where an approved editorial video was posted, with whatever metrics are available.
    Stored as a tracked ToonPost so the existing CultureToons analytics read it too."""
    from app.db import SessionLocal
    from app.models.toon_post import ToonPost
    from app.models.character_brand import CharacterBrand

    platform, post_url = body.get("platform"), (body.get("post_url") or "").strip()
    if platform not in ed.PLATFORMS:
        raise HTTPException(status_code=400, detail=f"platform must be one of {list(ed.PLATFORMS)}")
    if not post_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="post_url must be a full http(s) link")
    core, extra = _validated_metrics(body, require_core=True)
    posted_at = None
    if body.get("posted_at"):
        try:
            posted_at = datetime.fromisoformat(str(body["posted_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="posted_at must be an ISO date")

    session = SessionLocal()
    try:
        c = _get_candidate(session, candidate_id)
        if c.status not in ("approved", "published") or not c.toon_id:
            raise HTTPException(status_code=409, detail="Only an approved editorial video can be recorded as posted")
        reason = ed.editorial_gate(session, c.script_id)
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        brand = session.query(CharacterBrand).filter_by(id=c.brand_id).first()
        if brand is None:
            raise HTTPException(status_code=409, detail="The candidate's brand no longer exists")
        now = datetime.utcnow()
        post = ToonPost(
            toon_id=c.toon_id, brand_id=c.brand_id, user_id=brand.user_id, platform=platform, post_url=post_url,
            status="tracked", latest_views=core["views"], latest_likes=core["likes"],
            latest_comments=core["comments"], latest_shares=core["shares"], extra_metrics=extra or None,
            posted_at=posted_at or now, last_fetched_at=now,
        )
        session.add(post)
        c.status = "published"
        session.commit()
        return {"post_id": str(post.id), "candidate": serialize_candidate(c)}
    finally:
        session.close()


@router.post("/posts/{post_id}/metrics")
def update_post_metrics(post_id: str, body: dict):
    """Updates the metrics of a post recorded through this workflow. Missing fields stay as they
    were; a later reading should replace an earlier one, not add to it."""
    from app.db import SessionLocal
    from app.models.toon_post import ToonPost
    from app.models.editorial_candidate import EditorialCandidate

    core, extra = _validated_metrics(body, require_core=False)
    if not core and not extra:
        raise HTTPException(status_code=400, detail="Provide at least one metric")
    session = SessionLocal()
    try:
        post = session.query(ToonPost).filter_by(id=_uuid_or_404(post_id, "Post")).first()
        if post is None or not session.query(EditorialCandidate.id).filter_by(toon_id=post.toon_id).first():
            raise HTTPException(status_code=404, detail="Post not found in the editorial workflow")
        for field, value in core.items():
            setattr(post, f"latest_{field}", value)
        if extra:
            post.extra_metrics = {**(post.extra_metrics or {}), **extra}
        post.last_fetched_at = datetime.utcnow()
        session.commit()
        return {"post_id": str(post.id), "updated": sorted([*core, *extra])}
    finally:
        session.close()


@router.get("/performance")
def performance():
    from app.db import SessionLocal
    session = SessionLocal()
    try:
        return ed.performance_rows(session)
    finally:
        session.close()
