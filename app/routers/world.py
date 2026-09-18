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
from datetime import datetime
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
        "era_label": t.era_label,
        "era_year": t.era_year,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/features")
def list_world_features(region: Optional[str] = None, category: Optional[str] = None,
                         q: Optional[str] = None, era_only: bool = False,
                         era_year_min: Optional[int] = None,
                         era_year_max: Optional[int] = None, limit: int = 24, offset: int = 0):
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
        if era_only or era_year_min is not None or era_year_max is not None:
            # A Feature with no era_year at all isn't part of an era query —
            # only era-tagged Features should show up once the cursor's
            # historical zone is selected. era_only alone (no year bounds)
            # means "every era-tagged Feature for this region," for
            # TimeCursor's historical zone before any further year
            # refinement exists — cleaner than a magic-number sentinel range.
            query = query.filter(Toon.era_year.isnot(None))
            if era_year_min is not None:
                query = query.filter(Toon.era_year >= era_year_min)
            if era_year_max is not None:
                query = query.filter(Toon.era_year <= era_year_max)
        total = query.count()
        order = Toon.era_year.asc() if (era_only or era_year_min is not None or era_year_max is not None) else Toon.created_at.desc()
        rows = query.order_by(order).offset(offset).limit(limit).all()
        return {"features": [_serialize_feature(t) for t in rows], "total": total, "limit": limit, "offset": offset}
    finally:
        session.close()


@router.get("/regions")
def list_world_regions():
    """Regions with either published Features or real trend history.

    The map uses this combined surface so a country can be explored before
    its first video is published. ``count`` remains the published Feature
    count for backwards compatibility; the explicit trend fields describe
    the separate data layer shown on a region page.
    """
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.models.toon import Toon
    from sqlalchemy import func

    session = SessionLocal()
    try:
        feature_rows = (
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
        trend_rows = (
            session.query(Trend.region, func.count(Trend.id), func.count(func.distinct(func.date(Trend.collected_at))))
            .filter(Trend.region.isnot(None))
            .group_by(Trend.region)
            .all()
        )
        regions = {}
        for region, count in feature_rows:
            regions[region] = {"region": region, "count": count, "feature_count": count, "trend_count": 0, "trend_days": 0}
        for region, count, days in trend_rows:
            regions.setdefault(region, {"region": region, "count": 0, "feature_count": 0, "trend_count": 0, "trend_days": 0})
            regions[region]["trend_count"] = count
            regions[region]["trend_days"] = days
        return {"regions": sorted(regions.values(), key=lambda item: item["region"])}
    finally:
        session.close()


def _serialize_trend(t) -> dict:
    return {
        "id": t.id,
        "platform": t.platform,
        "title": t.title,
        "content": (t.content or "")[:280],
        "url": t.url,
        "likes": t.likes,
        "region": t.region,
        "collected_at": t.collected_at.isoformat() if t.collected_at else None,
    }


def _serialize_digest_signal(t) -> dict:
    return {
        "id": t.id,
        "platform": t.platform,
        "title": t.title,
        "likes": t.likes,
        "url": t.url,
        "collected_at": t.collected_at.isoformat() if t.collected_at else None,
    }


@router.get("/trends/digest")
def list_world_trend_digest(region: str, date_from: Optional[str] = None,
                            date_to: Optional[str] = None, limit: int = 8):
    """Human-readable trend groups for a region.

    Persisted Cluster summaries are the interpretation layer when available.
    Signals without a persisted cluster stay visibly labeled as source
    signals, grouped by platform rather than pretending a theme was inferred.
    """
    from app.db import SessionLocal
    from app.models.cluster import Cluster
    from app.models.trend import Trend

    limit = max(1, min(limit, 20))
    parsed_from, parsed_to = _parse_date(date_from), _parse_date(date_to)
    session = SessionLocal()
    try:
        query = session.query(Trend, Cluster).outerjoin(Cluster, Trend.cluster_id == Cluster.id)
        query = query.filter(Trend.region == region.strip().upper())
        if parsed_from:
            query = query.filter(Trend.collected_at >= parsed_from)
        if parsed_to:
            query = query.filter(Trend.collected_at <= parsed_to)
        rows = query.order_by(Trend.likes.desc().nullslast(), Trend.collected_at.desc()).limit(400).all()

        grouped = {}
        for trend, cluster in rows:
            if cluster:
                key = f"cluster:{cluster.id}"
                group = grouped.setdefault(key, {
                    "id": key, "kind": "cluster", "title": cluster.theme or "Emerging trend",
                    "summary": cluster.summary or "A recurring pattern across collected signals.",
                    "signal_count": 0, "platforms": set(), "signals": [],
                    "momentum": cluster.momentum,
                })
            else:
                key = f"source:{trend.platform}"
                group = grouped.setdefault(key, {
                    "id": key, "kind": "source", "title": f"{trend.platform.replace('_', ' ').title()} signals",
                    "summary": "Recent source signals awaiting enough evidence for a shared theme.",
                    "signal_count": 0, "platforms": set(), "signals": [], "momentum": None,
                })
            group["signal_count"] += 1
            group["platforms"].add(trend.platform)
            if len(group["signals"]) < 3:
                group["signals"].append(_serialize_digest_signal(trend))

        result = sorted(grouped.values(), key=lambda group: (-group["signal_count"], group["title"]))[:limit]
        for group in result:
            group["platforms"] = sorted(group["platforms"])
        return {"groups": result, "total_groups": len(grouped)}
    finally:
        session.close()


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {value!r} (expected ISO format, e.g. 2026-08-01)")


@router.get("/trends")
def list_world_trends(region: Optional[str] = None, date_from: Optional[str] = None,
                       date_to: Optional[str] = None, limit: int = 20, offset: int = 0):
    """Real trend data by region, separate from the generated-video Features
    above — "we will be providing all trends and videos to users" (this
    router's own name covers both). Same public/no-auth posture as the rest
    of this file; every field here is already public social-platform
    content (title/url/engagement counts), nothing account-scoped.

    date_from/date_to: ISO date/datetime strings, filtering Trend.collected_at
    — powers the World map's time-cursor "recent" zone (see GET /trends/coverage
    for the real per-region bounds to size that control against)."""
    from app.db import SessionLocal
    from app.models.trend import Trend

    limit = max(1, min(limit, 100))
    parsed_from, parsed_to = _parse_date(date_from), _parse_date(date_to)
    session = SessionLocal()
    try:
        query = session.query(Trend)
        if region:
            query = query.filter(Trend.region == region.strip().upper())
        if parsed_from:
            query = query.filter(Trend.collected_at >= parsed_from)
        if parsed_to:
            query = query.filter(Trend.collected_at <= parsed_to)
        total = query.count()
        rows = query.order_by(Trend.collected_at.desc()).offset(offset).limit(limit).all()
        return {"trends": [_serialize_trend(t) for t in rows], "total": total, "limit": limit, "offset": offset}
    finally:
        session.close()


@router.get("/trends/coverage")
def get_world_trends_coverage(region: str):
    """Real earliest/latest collected_at + a day count for one region — lets
    the frontend size the time-cursor's "recent" zone honestly instead of
    presenting a multi-week scrubber for a region with a single day of data
    (e.g. the 16 regions added in the 2026-09-18 coverage expansion) or a
    region with nothing at all (e.g. IR, which has zero Trend rows as of
    this writing despite having a published World Feature)."""
    from app.db import SessionLocal
    from app.models.trend import Trend
    from sqlalchemy import func

    session = SessionLocal()
    try:
        region_code = region.strip().upper()
        earliest, latest = (
            session.query(func.min(Trend.collected_at), func.max(Trend.collected_at))
            .filter(Trend.region == region_code)
            .first()
        )
        days_with_data = (
            session.query(func.count(func.distinct(func.date(Trend.collected_at))))
            .filter(Trend.region == region_code)
            .scalar()
        ) or 0
        return {
            "region": region_code,
            "earliest": earliest.isoformat() if earliest else None,
            "latest": latest.isoformat() if latest else None,
            "days_with_data": days_with_data,
        }
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
