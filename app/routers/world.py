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
import re

router = APIRouter(prefix="/world", tags=["world"])


def _publicly_visible():
    """SQL clause for a Feature a person has published. NULL is a Feature that
    was live before the publish gate existed, so it stays public."""
    from sqlalchemy import or_
    from app.models.toon import Toon
    return or_(Toon.world_published.is_(None), Toon.world_published.is_(True))


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
            _publicly_visible(),
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
        base_filters = [
            Toon.is_world_content.is_(True),
            Toon.status == "ready",
            _publicly_visible(),
            Toon.final_video_url.isnot(None),
        ]
        feature_rows = (
            session.query(Toon.subject_region, func.count(Toon.id))
            .filter(*base_filters, Toon.subject_region.isnot(None))
            .group_by(Toon.subject_region)
            .all()
        )
        # Genuinely global subjects (a species/phenomenon found worldwide, or a technology
        # with no single origin — see determine_world_region in world_production.py) are
        # deliberately never pinned to a country: a map marker implies "this happened here,"
        # and forcing one would misrepresent them. They're still fully real, published
        # Features though, just not geography-bound — surfaced to the map via this count
        # instead of a pin, so the globe can point to where they actually live (the
        # category browse grid on the same page) rather than going silently missing.
        global_feature_count = (
            session.query(func.count(Toon.id)).filter(*base_filters, Toon.subject_region.is_(None)).scalar()
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
        return {
            "regions": sorted(regions.values(), key=lambda item: item["region"]),
            "global_feature_count": global_feature_count or 0,
        }
    finally:
        session.close()


def _vs_usual_label(baseline: Optional[dict]) -> Optional[str]:
    """busier | quieter | normal — post volume versus the region's recent daily
    average; None when the region had too little history to compare."""
    return (baseline or {}).get("volume_dir")


@router.get("/regions/{code}/summary")
def get_region_summary(code: str, date: Optional[str] = None, lang: str = "en"):
    """The cached daily brief for a country (calendar + what people engaged
    with). Read-only: summaries are generated by the scheduler, so a public
    request can never trigger LLM spend. With no `date`, returns the most
    recent summary up to today. `summary` is null when none exists — a normal
    state for a region without enough data, not an error."""
    from app.db import SessionLocal
    from app.collectors.region_codes import region_name
    from app.translation import normalize_language, translate
    from app.models.region_daily_summary import RegionDailySummary

    region = code.strip().upper()
    if len(region) != 2 or not region.isalpha():
        raise HTTPException(status_code=400, detail="Invalid region code")
    lang = normalize_language(lang) or "en"
    wanted = _parse_date(date).date() if date else None

    session = SessionLocal()
    try:
        query = session.query(RegionDailySummary).filter(RegionDailySummary.region == region)
        if wanted:
            row = query.filter(RegionDailySummary.summary_date == wanted).first()
        else:
            row = query.filter(RegionDailySummary.summary_date <= datetime.utcnow().date()).order_by(
                RegionDailySummary.summary_date.desc()).first()
        empty = {"region": region, "region_name": region_name(region), "date": wanted.isoformat() if wanted else None,
                 "summary": None, "source": None, "calendar": [], "signal_count": 0, "platforms": [],
                 "mood": None, "sentiment": None, "alignment": None, "vs_usual": None, "generated_at": None,
                 "audience_matches": []}
        if not row:
            return empty
        # Summaries are written in English; a failed translation is reported, not hidden.
        translation = translate(row.summary, lang) if lang != "en" else None
        return {
            "region": region, "region_name": region_name(region), "date": row.summary_date.isoformat(),
            "summary": translation.text if translation else row.summary, "source": row.source,
            "translation_failed": bool(translation and not translation.ok),
            "calendar": row.calendar or [], "signal_count": row.signal_count,
            "platforms": row.platforms or [],
            "mood": row.mood, "sentiment": row.sentiment, "alignment": row.alignment,
            # Only a plain busier/quieter/normal label — the raw headlines stay internal.
            "vs_usual": _vs_usual_label(row.baseline),
            "generated_at": row.updated_at.isoformat() if row.updated_at else None,
            # Real audience archetypes matched against today's trends — see
            # region_daily_summary.py::top_persona_matches. Deterministic, not LLM-written.
            "audience_matches": row.audience_matches or [],
        }
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


_DIGEST_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "official", "video", "short",
    "news", "live", "new", "how", "why", "you", "your", "are", "was", "has", "have",
    "not", "will", "about", "into", "after", "over", "more", "what", "when", "where",
    "all", "的", "و", "في", "من", "على", "عن", "هذا", "هذه", "مع", "إلى",
}


def _digest_topic_tokens(trend) -> set[str]:
    text = f"{trend.title or ''} {(trend.content or '')[:180]}".lower()
    return {
        token for token in re.findall(r"[^\W_]{3,}", text, flags=re.UNICODE)
        if token not in _DIGEST_STOPWORDS and not token.isdigit()
    }


def _digest_title_key(trend) -> str:
    """Normalized text identity for one trend, used only to measure a group's
    diversity (app.services.trend_quality.score_group) — distinct keys among a
    group's signals versus its signal_count. Deliberately cruder than
    clean_title()/_normalize_key() in region_daily_summary.py (this doesn't need
    to produce a display-worthy title, only to tell "near-identical text" apart
    from "genuinely different posts")."""
    text = (trend.title or trend.content or "").lower()
    return re.sub(r"\W+", " ", text).strip()[:60]


def _add_source_digest_group(grouped: dict, trend) -> None:
    """Group unclustered signals by repeated title/content vocabulary.

    This is intentionally modest: it gives a reader a useful subject label
    without pretending that keyword overlap is the same thing as semantic
    or editorial interpretation. Persisted AI-labeled clusters remain the
    preferred context whenever they exist.
    """
    tokens = _digest_topic_tokens(trend)
    platform = trend.platform.replace("_", " ").title()
    candidate = None
    for group in grouped.values():
        if group["kind"] != "source" or group["platforms"] != {trend.platform}:
            continue
        overlap = len(tokens & group["topic_tokens"])
        if overlap >= 1 and overlap / max(1, len(tokens)) >= 0.2:
            candidate = group
            break
    if candidate is None:
        title = (trend.title or trend.content or "Untitled signal").strip()
        candidate = {
            "id": f"source:{trend.platform}:{len(grouped)}", "kind": "source",
            "title": f"{platform}: {title[:72]}",
            "summary": f"Automatic grouping of {platform} signals with overlapping topic words. Review the source examples below for the full context.",
            "signal_count": 0, "platforms": {trend.platform}, "signals": [],
            "momentum": None, "topic_tokens": set(tokens), "title_keys": set(),
        }
        grouped[candidate["id"]] = candidate
    candidate["signal_count"] += 1
    candidate["topic_tokens"].update(tokens)
    candidate["title_keys"].add(_digest_title_key(trend))
    if len(candidate["signals"]) < 3:
        candidate["signals"].append(_serialize_digest_signal(trend))


@router.get("/trends/digest")
def list_world_trend_digest(region: str, date_from: Optional[str] = None,
                            date_to: Optional[str] = None, limit: int = 8,
                            lang: str = "en"):
    """Human-readable trend groups for a region.

    Persisted Cluster summaries are the interpretation layer when available.
    Signals without a persisted cluster stay visibly labeled as source
    signals, grouped by platform rather than pretending a theme was inferred.
    """
    from app.db import SessionLocal
    from app.models.cluster import Cluster
    from app.models.trend import Trend
    from app.translation import normalize_language, translate_many
    from app.services.region_daily_summary import clean_title

    limit = max(1, min(limit, 20))
    lang = normalize_language(lang) or "en"
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
                    "momentum": cluster.momentum, "title_keys": set(),
                })
            else:
                # Confirmed live (2026-09-24): with no filter here at all, the #1 "trend" in
                # every region checked (US/GB/FR/NG/IN/BR) was either a bare TikTok audio-tag
                # label ("[Audio: original sound - ...]", 342 signals in US) or pure hashtag-
                # spam with no real caption text — clean_title() already exists and is tuned
                # for exactly this (region_daily_summary.py's daily-brief topic picker), just
                # never applied here. Only gates ungrouped signals: a trend already inside a
                # persisted, AI-labeled Cluster keeps counting toward it regardless of its own
                # caption quality — the cluster's theme/summary is the real interpretation
                # there, not any one member's raw text.
                if clean_title(trend.title or trend.content) is None:
                    continue
                _add_source_digest_group(grouped, trend)
                continue
            group["signal_count"] += 1
            group["platforms"].add(trend.platform)
            group["title_keys"].add(_digest_title_key(trend))
            if len(group["signals"]) < 3:
                group["signals"].append(_serialize_digest_signal(trend))

        # A persisted Cluster is an actual editorial theme; an ungrouped "source" bucket is just
        # raw signals sharing a platform, sometimes a single repeated hashtag caption with a huge
        # signal_count (confirmed live: a bare TikTok hashtag outranking a real curated theme).
        # score_group weighs persistence (Cluster.momentum), cross-platform corroboration, and
        # textual diversity (this exact spam case: one repeated caption, near-zero diversity)
        # ahead of raw size — see app/services/trend_quality.py for the full rationale.
        from app.services.trend_quality import score_group
        for group in grouped.values():
            group["_quality"] = score_group(
                signal_count=group["signal_count"], platforms=group["platforms"],
                title_keys=group["title_keys"], momentum=group["momentum"],
            ).score
        result = sorted(grouped.values(), key=lambda group: (-group["_quality"], group["title"]))[:limit]

        # One batched, cached translation call for the whole digest (was one
        # request per string on every page view, which trips Google's rate limit).
        texts, slots = [], []
        for group in result:
            texts.append(group["title"])
            slots.append((group, "title"))
            texts.append("Auto-grouped from similar signals." if group["kind"] == "source" else group["summary"])
            slots.append((group, "summary"))
            for signal in group["signals"]:
                texts.append(signal["title"] or "Untitled signal")
                slots.append((signal, "title"))
        translations = translate_many(texts, lang)
        for (target_dict, field), translation in zip(slots, translations):
            target_dict[field] = translation.text
        failed = sum(1 for t in translations if not t.ok)
        for group in result:
            group["platforms"] = sorted(group["platforms"])
            group.pop("topic_tokens", None)
            group.pop("title_keys", None)
            group.pop("_quality", None)
        return {"groups": result, "total_groups": len(grouped),
                # failed > 0: some text is shown untranslated because translation was unavailable
                "translation": {"lang": lang, "failed": failed}}
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
def get_world_feature(feature_id: str, lang: str = "en"):
    """A World video's own detail, plus its real narration as a text transcript — always stored and
    returned in English first (`shots[].dialogue`, in shot order, the exact lines the video's audio
    speaks), machine-translated into `lang` on request. This exists because dubbing every video into
    14 languages is neither cheap nor reliable, but the narration text is already real and already
    sitting in the database — a transcript is a text-translation problem, which this platform's
    translation service (app/translation/service.py) already handles well, not an audio problem."""
    from app.db import SessionLocal
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript
    from app.translation import normalize_language, translate_many

    session = SessionLocal()
    try:
        try:
            toon_uuid = _uuid.UUID(feature_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Feature not found")
        toon = session.query(Toon).filter_by(id=toon_uuid).first()
        if (not toon or not toon.is_world_content or toon.status != "ready" or not toon.final_video_url
                or toon.world_published is False):
            raise HTTPException(status_code=404, detail="Feature not found")
        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        result = _serialize_feature(toon)
        hook_line = script.hook_line if script else None
        transcript = [line for sh in ((script.shots if script else None) or [])
                      if (line := (sh.get("dialogue") or "").strip())]

        target = normalize_language(lang) or "en"
        translation_failed = False
        if target != "en":
            texts = ([hook_line] if hook_line else []) + transcript
            translated = translate_many(texts, target)
            translation_failed = any(not t.ok for t in translated)
            if hook_line:
                hook_line, transcript = translated[0].text, [t.text for t in translated[1:]]
            else:
                transcript = [t.text for t in translated]

        result["hook_line"] = hook_line
        result["duration_seconds"] = script.total_duration_seconds if script else None
        result["transcript"] = transcript
        result["transcript_language"] = target
        result["translation_failed"] = translation_failed
        result["source"] = None
        if toon.curated_item_id:
            from app.models.curated_item import CuratedItem
            from app.services.world_production import source_label
            item = session.query(CuratedItem).filter_by(id=toon.curated_item_id).first()
            if item and item.source_url:
                result["source"] = {"label": source_label(item), "url": item.source_url}
        return result
    finally:
        session.close()
