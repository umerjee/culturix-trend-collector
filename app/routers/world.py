"""Public read surface for World Features — subject-centric content (a
place/phenomenon/species is the star, character optional) shown at
culturix-web's /world section. See app/models/toon.py's is_world_content
docstring and the World Features plan.

Deliberately NOT mounted under culturetoons_router (see app/main.py's
app.include_router call): every route there carries
dependencies=[Depends(require_internal_secret)], the Railway<->Vercel
inter-service secret gating every other /api/* route. This is meant to be
genuinely public — no end-user auth AND no internal secret — so it follows
GET /regions's existing precedent (app/main.py) as the one other endpoint
in this codebase that's intentionally ungated, rather than living under
/api/* where "gated" is otherwise a safe assumption. Every query here is
read-only and pre-filtered to is_world_content=True AND status='ready' —
no ordinary user's private Toons are ever reachable through this router."""
from fastapi import APIRouter, HTTPException
from typing import Optional
import uuid as _uuid

router = APIRouter(prefix="/world", tags=["world"])


def _serialize_feature(t) -> dict:
    return {
        "id": str(t.id),
        "title": t.title,
        "subject_region": t.subject_region,
        "subject_text": t.subject_text,
        "subject_category": t.subject_category,
        "final_video_url": t.final_video_url,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/features")
def list_world_features(region: Optional[str] = None, category: Optional[str] = None,
                         q: Optional[str] = None, limit: int = 24, offset: int = 0):
    from app.db import SessionLocal
    from app.models.toon import Toon

    limit = max(1, min(limit, 100))
    session = SessionLocal()
    try:
        query = session.query(Toon).filter(
            Toon.is_world_content.is_(True),
            Toon.status == "ready",
            Toon.final_video_url.isnot(None),
        )
        if region:
            query = query.filter(Toon.subject_region == region.strip().upper())
        if category:
            query = query.filter(Toon.subject_category == category.strip().lower())
        if q:
            query = query.filter(Toon.subject_text.ilike(f"%{q.strip()}%"))
        total = query.count()
        rows = query.order_by(Toon.created_at.desc()).offset(offset).limit(limit).all()
        return {"features": [_serialize_feature(t) for t in rows], "total": total, "limit": limit, "offset": offset}
    finally:
        session.close()


@router.get("/regions")
def list_world_regions():
    """Distinct regions that actually have ready World content, with a
    count each — separate from the full target-region catalog served by
    GET /regions (that one lists every region the product can be
    configured for, regardless of whether any content exists there yet;
    the map needs "has content", not the full catalog)."""
    from app.db import SessionLocal
    from app.models.toon import Toon
    from sqlalchemy import func

    session = SessionLocal()
    try:
        rows = (
            session.query(Toon.subject_region, func.count(Toon.id))
            .filter(
                Toon.is_world_content.is_(True),
                Toon.status == "ready",
                Toon.final_video_url.isnot(None),
                Toon.subject_region.isnot(None),
            )
            .group_by(Toon.subject_region)
            .all()
        )
        return {"regions": [{"region": r, "count": c} for r, c in rows]}
    finally:
        session.close()


@router.get("/features/{feature_id}")
def get_world_feature(feature_id: str):
    from app.db import SessionLocal
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript

    session = SessionLocal()
    try:
        try:
            toon_uuid = _uuid.UUID(feature_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Feature not found")
        toon = session.query(Toon).filter_by(id=toon_uuid).first()
        if not toon or not toon.is_world_content or toon.status != "ready" or not toon.final_video_url:
            raise HTTPException(status_code=404, detail="Feature not found")
        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        result = _serialize_feature(toon)
        result["hook_line"] = script.hook_line if script else None
        return result
    finally:
        session.close()
