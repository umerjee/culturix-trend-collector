import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_):
    # Ensure all tables exist (safe to run on every startup — create_all is idempotent)
    from app.db import Base, engine
    from app.models.trend import Trend                          # noqa: F401
    from app.models.persona import Persona                      # noqa: F401
    from app.models.trendpersona import TrendPersona            # noqa: F401
    from app.models.cluster import Cluster                      # noqa: F401
    from app.models.user_profile import UserProfile             # noqa: F401
    from app.models.generated_content import GeneratedContent   # noqa: F401
    from app.models.content_profile import ContentProfile       # noqa: F401
    from app.models.generated_media import GeneratedMedia       # noqa: F401
    from app.models.content_check_log import ContentCheckLog    # noqa: F401
    from app.models.trend_validation_log import TrendValidationLog  # noqa: F401
    from app.models.trend_theme import TrendTheme                  # noqa: F401
    from app.models.trend_occurrence import TrendOccurrence         # noqa: F401
    from app.models.high_velocity_alert import HighVelocityAlert    # noqa: F401
    from app.models.connected_account import ConnectedAccount       # noqa: F401
    from app.models.content_post import ContentPost                 # noqa: F401
    from app.models.content_post_snapshot import ContentPostSnapshot  # noqa: F401
    from app.models.integration_health import IntegrationHealth       # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Add columns introduced after initial deploy (idempotent).
    # Each statement commits (and, on failure, rolls back) independently —
    # startup must never go down because one DDL statement in this list
    # failed against unexpected existing data (e.g. CREATE UNIQUE INDEX
    # failing because duplicate rows already exist would otherwise abort the
    # whole transaction and prevent every later statement from applying too).
    from sqlalchemy import text as _text
    with engine.connect() as _conn:
        for _stmt in [
            "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS approved BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
            "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'free'",
            "ALTER TABLE generated_content ADD COLUMN IF NOT EXISTS content_profile_id UUID",
            # generated_media table is created by create_all above; index added here in case of race
            "CREATE INDEX IF NOT EXISTS idx_generated_media_content ON generated_media(generated_content_id, idea_index)",
            # Incremental clustering/personas: reuse unchanged clusters instead of full rebuild
            "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64)",
            "CREATE INDEX IF NOT EXISTS idx_clusters_fingerprint ON clusters(fingerprint)",
            "ALTER TABLE personas ADD COLUMN IF NOT EXISTS cluster_id INTEGER",
            "CREATE INDEX IF NOT EXISTS idx_personas_cluster_id ON personas(cluster_id)",
            # Stripe self-serve billing
            "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)",
            "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255)",
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_stripe_customer ON user_profiles(stripe_customer_id)",
            # Cluster momentum (up/down/neutral trend direction)
            "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS momentum VARCHAR(10)",
            "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS previous_size INTEGER",
            # Velocity scoring pipeline (scraping/culturix_scraping/) — likes/hour proxy
            "ALTER TABLE trends ADD COLUMN IF NOT EXISTS velocity_score FLOAT",
            # ON CONFLICT (platform, external_id) in the async upsert pipeline needs
            # a real unique index to target — collectors dedup at the app level
            # before insert, but that check isn't atomic, so this can plausibly
            # fail against real production data if any duplicates ever slipped
            # through a race; caught below rather than allowed to crash startup.
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_trends_platform_external_id ON trends(platform, external_id)",
            # Phase 1 — closed feedback loop (connected accounts / publish+track)
            "ALTER TABLE content_profiles ADD COLUMN IF NOT EXISTS publish_mode VARCHAR(10) NOT NULL DEFAULT 'manual'",
            "CREATE INDEX IF NOT EXISTS idx_content_posts_content ON content_posts(generated_content_id, idea_index)",
            "CREATE INDEX IF NOT EXISTS idx_content_post_snapshots_post ON content_post_snapshots(content_post_id)",
            # Preferred content format (video/photo/text) — empty means unrestricted
            "ALTER TABLE content_profiles ADD COLUMN IF NOT EXISTS preferred_formats TEXT[] DEFAULT '{}'",
            # Region tagging — NULL means unknown (fail-open in persona_mapper.py's
            # filter), not "no region." Historical rows stay NULL (not backfillable).
            "ALTER TABLE trends ADD COLUMN IF NOT EXISTS region VARCHAR(10)",
            # Real per-post image (YouTube's stable thumbnail, or TikTok's cover
            # re-hosted to Supabase Storage at collection time) — used as an
            # optional reference for image generation. NULL means unavailable.
            "ALTER TABLE trends ADD COLUMN IF NOT EXISTS image_url TEXT",
            # Binds a connected account to one specific ContentProfile (niche) —
            # a user's own dedicated "avatar account" for that niche. NULL stays
            # legacy/user-wide; see app/models/connected_account.py.
            "ALTER TABLE connected_accounts ADD COLUMN IF NOT EXISTS content_profile_id UUID",
            "ALTER TABLE connected_accounts DROP CONSTRAINT IF EXISTS uq_connected_accounts_user_platform",
            "ALTER TABLE connected_accounts ADD CONSTRAINT uq_connected_accounts_profile_platform UNIQUE (content_profile_id, platform)",
            # Which weekday a "weekly" delivery profile's digest email goes out
            # on (0=Monday..6=Sunday) — ignored for "daily". User-picked, not
            # derived from anything, per an explicit product decision.
            "ALTER TABLE content_profiles ADD COLUMN IF NOT EXISTS delivery_day_of_week INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                _conn.execute(_text(_stmt))
                _conn.commit()
            except Exception as _migration_err:
                logging.getLogger("culturix.startup").warning(
                    "Startup migration statement failed, skipping: %s | %s", _stmt, _migration_err
                )
                _conn.rollback()
        # Grandfather all users who existed before the approval gate was added
        _conn.execute(_text(
            "UPDATE user_profiles SET approved = TRUE WHERE approved = FALSE AND created_at IS NULL"
        ))
        _conn.commit()

    # Migrate existing UserProfile rows into content_profiles (one-time, idempotent)
    from sqlalchemy import text as _text2
    with engine.connect() as _conn2:
        _conn2.execute(_text2("""
            INSERT INTO content_profiles
                (id, user_id, name, industry_niche, target_platforms, target_regions,
                 content_goals, content_tones, persona_tags,
                 target_age_min, target_age_max, delivery_freq, delivery_time,
                 is_active, created_at, updated_at)
            SELECT
                gen_random_uuid(), user_id, 'My Profile', industry_niche,
                target_platforms, target_regions, content_goals, content_tones,
                persona_tags, target_age_min, target_age_max,
                delivery_freq, delivery_time, TRUE, NOW(), NOW()
            FROM user_profiles up
            WHERE NOT EXISTS (
                SELECT 1 FROM content_profiles cp WHERE cp.user_id = up.user_id
            )
        """))
        _conn2.commit()

    # Ensure superadmin always has a plan='pro' user_profiles row
    import os as _os
    _superadmin_id = _os.getenv("SUPERADMIN_USER_ID", "")
    if _superadmin_id:
        from sqlalchemy import text as _text3
        with engine.connect() as _conn3:
            _conn3.execute(_text3("""
                INSERT INTO user_profiles
                    (id, user_id, approved, plan, created_at,
                     target_age_min, target_age_max, target_platforms, target_regions,
                     content_goals, content_tones, industry_niche, persona_tags,
                     delivery_freq, delivery_time)
                VALUES
                    (gen_random_uuid(), :uid, TRUE, 'pro', NOW(),
                     18, 35, '{}', '{}', '{}', '{}', 'general', '{}', 'daily', '07:00')
                ON CONFLICT (user_id) DO UPDATE SET plan = 'pro', approved = TRUE
            """), {"uid": _superadmin_id})
            _conn3.commit()

    from app.scheduler import start, stop
    start()
    yield
    stop()
from fastapi.middleware.cors import CORSMiddleware
from app.personas import (
    generate_personas_for_recent_trends,
    generate_clustered_personas,
    generate_suggestions_for_persona,
)

app = FastAPI(title="Culturix API", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://culturix-web.vercel.app",
        "https://culturix-trend-collector.vercel.app",
        "https://culturix-trend-collector-production.up.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Collectors ────────────────────────────────────────────────────────────────

@app.post("/collect/reddit")
def collect_reddit():
    from app.collectors.reddit import store_reddit_trends
    return {"inserted": store_reddit_trends()}


@app.post("/collect/tiktok")
def collect_tiktok(region: str = "US"):
    from app.collectors.tiktok import store_tiktok_trends
    return {"inserted": store_tiktok_trends(region=region)}


@app.post("/collect/youtube")
def collect_youtube(region: str = "US"):
    from app.collectors.youtube import store_youtube_trends, fetch_youtube_trending
    items = fetch_youtube_trending(region, limit=1)
    if items:
        return {"inserted": store_youtube_trends(region)}
    return {
        "inserted": 0,
        "warning": (
            "YouTube Data API disabled or API key invalid. "
            "Enable the YouTube Data API v3 in Google Cloud Console: "
            "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
        ),
    }


@app.post("/collect/twitter")
def collect_twitter(region: str = "global"):
    """Same Apify-primary/proxy-fallback path the scheduled orchestrator uses
    (app.collectors.twitter.store_twitter_trends). `region` only affects the
    proxy fallback branch — the Apify actor searches fixed queries, not
    per-region terms, so it's ignored when that branch succeeds."""
    from app.collectors.twitter import store_twitter_trends

    inserted = store_twitter_trends(region)
    return {"inserted": inserted}


# ── Processing ────────────────────────────────────────────────────────────────

@app.post("/process/translations")
def run_translations(limit: int = 1000):
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.language import detect_language, translate_to_english_if_needed

    session = SessionLocal()
    try:
        trends = session.query(Trend).order_by(Trend.id.desc()).limit(limit).all()
        updated = 0
        for t in trends:
            text = t.content or t.title or ""
            if not text.strip():
                continue
            lang = detect_language(text)
            t.language = lang
            t.translated_content = translate_to_english_if_needed(text, lang)
            updated += 1
        session.commit()
        return {"updated": updated}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.post("/process/embeddings")
def run_embeddings(limit: int = 500):
    from app.embedding_processor import process_embeddings
    return {"embedded": process_embeddings(limit)}


@app.post("/process/personas")
def process_personas():
    return generate_personas_for_recent_trends(limit=50)


@app.post("/process/personas/clustered")
def process_clustered_personas():
    return generate_clustered_personas(limit=200, min_cluster_size=5)


@app.post("/process/cluster")
def process_cluster(limit: int = 500, min_cluster_size: int = 5):
    from app.clustering_service import run_clustering
    return run_clustering(limit=limit, min_cluster_size=min_cluster_size)


# ── Trends ────────────────────────────────────────────────────────────────────

@app.get("/trends/latest")
def trends_latest(
    limit: int = 50,
    offset: int = 0,
    platform: str = None,
    language: str = None,
):
    from app.db import SessionLocal
    from app.models.trend import Trend

    session = SessionLocal()
    try:
        q = session.query(Trend).order_by(Trend.collected_at.desc())
        if platform:
            q = q.filter(Trend.platform == platform)
        if language:
            q = q.filter(Trend.language == language)
        trends = q.offset(offset).limit(limit).all()
        return [
            {
                "id": t.id,
                "platform": t.platform,
                "title": t.title,
                "content": t.content,
                "translated_content": t.translated_content,
                "language": t.language,
                "url": t.url,
                "author": t.author,
                "likes": t.likes,
                "comments": t.comments,
                "views": t.views,
                "cluster_id": t.cluster_id,
                "collected_at": t.collected_at,
                "posted_at": t.posted_at,
            }
            for t in trends
        ]
    finally:
        session.close()


@app.get("/trends/{trend_id}")
def get_trend(trend_id: int):
    from app.db import SessionLocal
    from app.models.trend import Trend

    session = SessionLocal()
    try:
        trend = session.query(Trend).filter(Trend.id == trend_id).first()
        if not trend:
            raise HTTPException(status_code=404, detail="Trend not found")
        return {
            "id": trend.id,
            "platform": trend.platform,
            "title": trend.title,
            "content": trend.content,
            "translated_content": trend.translated_content,
            "language": trend.language,
            "url": trend.url,
            "author": trend.author,
            "likes": trend.likes,
            "comments": trend.comments,
            "views": trend.views,
            "cluster_id": trend.cluster_id,
            "collected_at": trend.collected_at,
            "posted_at": trend.posted_at,
        }
    finally:
        session.close()


@app.get("/search")
def search_trends(q: str, limit: int = 20, platform: str = None):
    from app.db import SessionLocal
    from app.models.trend import Trend

    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

    session = SessionLocal()
    try:
        query = session.query(Trend).filter(
            Trend.translated_content.ilike(f"%{q}%")
            | Trend.title.ilike(f"%{q}%")
            | Trend.content.ilike(f"%{q}%")
        )
        if platform:
            query = query.filter(Trend.platform == platform)
        trends = query.order_by(Trend.collected_at.desc()).limit(limit).all()
        return [
            {
                "id": t.id,
                "platform": t.platform,
                "title": t.title,
                "translated_content": t.translated_content,
                "language": t.language,
                "url": t.url,
                "cluster_id": t.cluster_id,
                "collected_at": t.collected_at,
            }
            for t in trends
        ]
    finally:
        session.close()


# ── Clusters ──────────────────────────────────────────────────────────────────

@app.get("/clusters")
def list_clusters(limit: int = 50, offset: int = 0):
    from app.db import SessionLocal
    from app.models.cluster import Cluster
    from app.models.trend import Trend

    session = SessionLocal()
    try:
        clusters = (
            session.query(Cluster)
            .order_by(Cluster.size.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        result = []
        for c in clusters:
            sample = (
                session.query(Trend)
                .filter(Trend.cluster_id == c.id)
                .order_by(Trend.collected_at.desc())
                .limit(5)
                .all()
            )
            result.append({
                "id": c.id,
                "label": c.label,
                "theme": c.theme,
                "summary": c.summary,
                "size": c.size,
                "created_at": c.created_at,
                "sample_trends": [
                    {"id": t.id, "platform": t.platform, "title": t.title}
                    for t in sample
                ],
            })
        return result
    finally:
        session.close()


@app.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: int, limit: int = 50):
    from app.db import SessionLocal
    from app.models.cluster import Cluster
    from app.models.trend import Trend

    session = SessionLocal()
    try:
        cluster = session.query(Cluster).filter(Cluster.id == cluster_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster not found")
        trends = (
            session.query(Trend)
            .filter(Trend.cluster_id == cluster_id)
            .order_by(Trend.collected_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "id": cluster.id,
            "label": cluster.label,
            "theme": cluster.theme,
            "summary": cluster.summary,
            "size": cluster.size,
            "created_at": cluster.created_at,
            "trends": [
                {
                    "id": t.id,
                    "platform": t.platform,
                    "title": t.title,
                    "url": t.url,
                    "collected_at": t.collected_at,
                }
                for t in trends
            ],
        }
    finally:
        session.close()


@app.get("/recommendations")
def get_recommendations(persona_id: int = None, cluster_id: int = None, limit: int = 10):
    """
    Returns content suggestions.
    - If persona_id given: return that persona's content_suggestions.
    - If cluster_id given: return trends in that cluster as recommended content.
    - If neither: return the most-liked trends across all platforms.
    """
    from app.db import SessionLocal
    from app.models.persona import Persona
    from app.models.trend import Trend

    session = SessionLocal()
    try:
        if persona_id:
            persona = session.query(Persona).filter(Persona.id == persona_id).first()
            if not persona:
                raise HTTPException(status_code=404, detail="Persona not found")
            suggestions = json.loads(persona.content_suggestions) if persona.content_suggestions else []
            return {
                "persona_id": persona_id,
                "persona_name": persona.name,
                "recommendations": suggestions,
            }

        if cluster_id:
            trends = (
                session.query(Trend)
                .filter(Trend.cluster_id == cluster_id)
                .order_by(Trend.likes.desc().nullslast())
                .limit(limit)
                .all()
            )
            return {
                "cluster_id": cluster_id,
                "recommendations": [
                    {"id": t.id, "platform": t.platform, "title": t.title, "url": t.url, "likes": t.likes}
                    for t in trends
                ],
            }

        # Default: top trends by engagement
        trends = (
            session.query(Trend)
            .order_by(Trend.likes.desc().nullslast())
            .limit(limit)
            .all()
        )
        return {
            "recommendations": [
                {"id": t.id, "platform": t.platform, "title": t.title, "url": t.url, "likes": t.likes}
                for t in trends
            ]
        }
    finally:
        session.close()


# ── Personas & Suggestions ────────────────────────────────────────────────────

@app.get("/personas")
def list_personas(limit: int = 50, offset: int = 0):
    from app.db import SessionLocal
    from app.models.persona import Persona

    session = SessionLocal()
    try:
        personas = (
            session.query(Persona)
            .order_by(Persona.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "motivations": p.motivations,
                "interests": p.interests,
                "content_suggestions": json.loads(p.content_suggestions) if p.content_suggestions else None,
                "created_at": p.created_at,
            }
            for p in personas
        ]
    finally:
        session.close()


@app.get("/personas/{persona_id}")
def get_persona(persona_id: int):
    from app.db import SessionLocal
    from app.models.persona import Persona
    from app.models.trendpersona import TrendPersona
    from app.models.trend import Trend

    session = SessionLocal()
    try:
        persona = session.query(Persona).filter(Persona.id == persona_id).first()
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")

        linked = (
            session.query(Trend)
            .join(TrendPersona, TrendPersona.trend_id == Trend.id)
            .filter(TrendPersona.persona_id == persona_id)
            .order_by(Trend.collected_at.desc())
            .limit(20)
            .all()
        )

        return {
            "id": persona.id,
            "name": persona.name,
            "description": persona.description,
            "motivations": persona.motivations,
            "interests": persona.interests,
            "content_suggestions": json.loads(persona.content_suggestions) if persona.content_suggestions else None,
            "created_at": persona.created_at,
            "sample_trends": [
                {"id": t.id, "platform": t.platform, "title": t.title, "url": t.url}
                for t in linked
            ],
        }
    finally:
        session.close()


@app.post("/personas/{persona_id}/suggestions")
def refresh_suggestions(persona_id: int):
    result = generate_suggestions_for_persona(persona_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Workstream 1 — User Profiles & Digest ─────────────────────────────────────

@app.post("/api/users/profile")
def save_user_profile(profile: dict):
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile

    session = SessionLocal()
    try:
        user_id = profile.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")

        existing = session.query(UserProfile).filter_by(user_id=user_id).first()
        if existing:
            for field in [
                "target_age_min", "target_age_max", "target_platforms", "target_regions",
                "content_goals", "content_tones", "industry_niche", "persona_tags",
                "delivery_freq", "delivery_time",
            ]:
                if field in profile:
                    setattr(existing, field, profile[field])
            session.commit()
            return {"status": "updated", "id": str(existing.id)}
        else:
            p = UserProfile(
                user_id=user_id,
                target_age_min=profile.get("target_age_min", 18),
                target_age_max=profile.get("target_age_max", 35),
                target_platforms=profile.get("target_platforms", []),
                target_regions=profile.get("target_regions", []),
                content_goals=profile.get("content_goals", []),
                content_tones=profile.get("content_tones", []),
                industry_niche=profile.get("industry_niche"),
                persona_tags=profile.get("persona_tags", []),
                delivery_freq=profile.get("delivery_freq", "daily"),
                delivery_time=profile.get("delivery_time", "07:00"),
            )
            session.add(p)
            session.commit()
            return {"status": "created", "id": str(p.id)}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.get("/api/users/profile")
def get_user_profile(user_id: str):
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile

    session = SessionLocal()
    try:
        p = session.query(UserProfile).filter_by(user_id=user_id).first()
        if not p:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {
            "user_id": str(p.user_id),
            "target_age_min": p.target_age_min,
            "target_age_max": p.target_age_max,
            "target_platforms": p.target_platforms or [],
            "target_regions": p.target_regions or [],
            "content_goals": p.content_goals or [],
            "content_tones": p.content_tones or [],
            "industry_niche": p.industry_niche,
            "persona_tags": p.persona_tags or [],
            "delivery_freq": p.delivery_freq,
            "delivery_time": p.delivery_time,
        }
    finally:
        session.close()


@app.get("/api/digest/{user_id}")
def get_digest(user_id: str, profile_id: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.generated_content import GeneratedContent
    import uuid as _uuid

    session = SessionLocal()
    try:
        q = session.query(GeneratedContent).filter(
            GeneratedContent.user_id == _uuid.UUID(user_id)
        )
        if profile_id:
            q = q.filter(GeneratedContent.content_profile_id == _uuid.UUID(profile_id))
        # nullslast(): Postgres defaults to NULLS FIRST on DESC, and every
        # digest created before the generated_at insert fix was NULL — without
        # this, a legacy NULL row could outrank a genuinely newer one, which
        # is exactly what "shows old suggestions, not new" turned out to be.
        latest = q.order_by(GeneratedContent.generated_at.desc().nullslast()).first()
        if not latest:
            raise HTTPException(status_code=404, detail="No digest yet")
        return {
            "id": str(latest.id),
            "user_id": str(latest.user_id),
            "content_profile_id": str(latest.content_profile_id) if latest.content_profile_id else None,
            "generated_at": latest.generated_at,
            "trend_date": str(latest.trend_date),
            "clusters": latest.clusters or [],
            "content_ideas": latest.content_ideas or [],
            "delivered": latest.delivered,
        }
    finally:
        session.close()


@app.post("/api/generate-idea")
def generate_idea_for_trend(body: dict):
    """On-demand content generation for a single trend — the dashboard proactively
    generates one idea for each user's top 3 (most relevant) trends at digest-build
    time; every other trend shows a 'Generate content' button that hits this
    endpoint instead of costing a generation call unless someone actually wants it.

    Idempotent per (content_id, cluster_index): once an idea exists for a trend, this
    just returns it — no regeneration. A prior failed attempt never appended anything,
    so retrying after a failure still works naturally without any extra bookkeeping.
    """
    from app.db import SessionLocal
    from app.models.generated_content import GeneratedContent
    from app.models.content_profile import ContentProfile
    from app.pipeline.nodes.content_strategist import _generate_ideas_for_clusters
    from app.pipeline.nodes.trend_validator import _validate_ideas_via_llm
    from sqlalchemy.orm.attributes import flag_modified
    import uuid as _uuid

    content_id = body.get("content_id")
    cluster_index = body.get("cluster_index")
    if content_id is None or cluster_index is None:
        raise HTTPException(status_code=400, detail="content_id and cluster_index required")

    session = SessionLocal()
    try:
        content = session.query(GeneratedContent).filter_by(id=_uuid.UUID(content_id)).first()
        if not content:
            raise HTTPException(status_code=404, detail="Digest not found")

        clusters = content.clusters or []
        if not (0 <= cluster_index < len(clusters)):
            raise HTTPException(status_code=400, detail="cluster_index out of range for this digest")

        ideas = content.content_ideas or []
        existing_index, existing = next(
            ((i, idea) for i, idea in enumerate(ideas) if idea.get("cluster_index") == cluster_index),
            (None, None),
        )
        if existing:
            # idea_index (its position in content_ideas — what GeneratedMedia/ContentPost
            # key off of) is NOT the same as cluster_index once on-demand ideas start
            # getting appended out of cluster order — always return it explicitly rather
            # than let the frontend guess/recompute it.
            return {**existing, "idea_index": existing_index}

        profile = None
        if content.content_profile_id:
            profile = session.query(ContentProfile).filter_by(id=content.content_profile_id).first()
        profile_dict = {
            "industry_niche": profile.industry_niche if profile else None,
            "target_platforms": profile.target_platforms if profile else [],
            "content_tones": profile.content_tones if profile else [],
            "content_goals": profile.content_goals if profile else [],
            "persona_tags": profile.persona_tags if profile else [],
            "target_age_min": profile.target_age_min if profile else 18,
            "target_age_max": profile.target_age_max if profile else 35,
            "preferred_formats": profile.preferred_formats if profile else [],
        }

        try:
            generated = _generate_ideas_for_clusters(profile_dict, [clusters[cluster_index]], top_signals=[])
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Idea generation failed: {e}")
        if not generated:
            raise HTTPException(status_code=503, detail="Idea generation returned nothing — try again")
        idea = generated[0]

        try:
            validations = _validate_ideas_via_llm([idea])
            v = validations[0] if validations else {"safe": True, "coherent": True, "specific": True}
        except Exception:
            v = {"safe": True, "coherent": True, "specific": True}  # fail-open, matches trend_validator.py's own policy
        if not (v.get("safe", True) and v.get("coherent", True) and v.get("specific", True)):
            raise HTTPException(
                status_code=422,
                detail=f"Generated idea didn't pass quality review ({v.get('reason', 'no reason given')}) — try again"
            )

        idea["cluster_index"] = cluster_index
        idea["source"] = "on_demand"
        new_idea_index = len(ideas)
        ideas.append(idea)
        content.content_ideas = ideas
        flag_modified(content, "content_ideas")
        session.commit()
        return {**idea, "idea_index": new_idea_index}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/generate")
def trigger_generation(body: dict):
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    import threading
    def _run():
        try:
            from app.pipeline.graph import run_pipeline
            run_pipeline()
        except Exception as e:
            logging.error("On-demand pipeline failed: %s", e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "pipeline_started", "user_id": user_id}


@app.post("/api/generate-media")
def request_generate_media(body: dict, background_tasks: BackgroundTasks):
    """
    Body: {
      content_id: str,
      idea_index: int,
      user_id: str,
      media_types: ["voiceover", "music", "video", "image"],   # subset allowed
      prompts: { voiceover: str, music: str, video: str, image: str }
    }
    Inserts generated_media rows (status=pending) and queues background generation.
    Returns immediately with the created row IDs.
    """
    from app.db import SessionLocal
    from app.models.generated_media import GeneratedMedia
    from app.models.user_profile import UserProfile
    from app.media.service import run_generation
    import uuid as _uuid

    content_id = body.get("content_id")
    idea_index = body.get("idea_index")
    user_id = body.get("user_id")
    media_types: List[str] = body.get("media_types", [])
    prompts: dict = body.get("prompts", {})

    if not content_id or idea_index is None or not user_id or not media_types:
        raise HTTPException(status_code=400, detail="content_id, idea_index, user_id, media_types required")

    VALID = {"voiceover", "music", "video", "image"}
    media_types = [m for m in media_types if m in VALID]
    if not media_types:
        raise HTTPException(status_code=400, detail="No valid media_types (voiceover|music|video|image)")

    # Plan-tier gating: free users cannot generate media
    # Superadmin (SUPERADMIN_USER_ID env var) always bypasses this check
    from app.media.quota import plan_blocks_media, quota_exceeded, MONTHLY_QUOTA
    _superadmin_id = os.getenv("SUPERADMIN_USER_ID", "")
    if user_id != _superadmin_id:
        session = SessionLocal()
        try:
            profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
            plan = (profile.plan or "free") if profile else "free"
            if plan_blocks_media(plan):
                raise HTTPException(status_code=403, detail="Media generation is a Pro feature. Upgrade to generate voiceovers, music, and video.")

            # Check monthly quota (pro: 50 generations/month)
            from sqlalchemy import text as _text
            month_count = session.execute(_text("""
                SELECT COUNT(*) FROM generated_media gm
                JOIN generated_content gc ON gc.id = gm.generated_content_id
                WHERE gc.user_id = :uid
                  AND gm.created_at >= date_trunc('month', now())
            """), {"uid": _uuid.UUID(user_id)}).scalar() or 0
            if quota_exceeded(month_count, len(media_types)):
                raise HTTPException(
                    status_code=429,
                    detail=f"Monthly media quota reached ({MONTHLY_QUOTA} generations). Resets on the 1st."
                )
        finally:
            session.close()

    # Pre-flight: ensure API keys are configured before wasting a DB row on a doomed job.
    # voiceover uses edge-tts (free, no API key) so it's intentionally not in this map.
    _KEY_CHECK = {
        "music":     ("SUNO_API_KEY",       "MiniMax (via aimlapi)"),
        "video":     ("KLING_ACCESS_KEY",   "Kling"),
        "image":     ("QWEN_API_KEY",       "Qwen-Image"),
    }
    missing_keys = [
        f"{mt} ({name}): add {env_var} to Railway env vars"
        for mt in media_types
        for check in [_KEY_CHECK.get(mt)]
        if check
        for env_var, name in [check]
        if not os.getenv(env_var)
    ]
    if missing_keys:
        raise HTTPException(
            status_code=503,
            detail="Media provider not configured — " + "; ".join(missing_keys)
        )

    _PROVIDER_MAP = {"voiceover": "edge-tts", "music": "minimax", "video": "kling", "image": "qwen-image-2.0"}
    created_ids = []
    session2 = SessionLocal()
    try:
        # Resolve a real reference photo for image generation, if this idea's
        # trend cluster has one (see clusterer.py's _tag_cluster_reference_image) —
        # grounds the generated image in reality instead of a blind text guess.
        # Fails open to None on any lookup miss; image generation just falls
        # back to today's pure text-to-image behavior.
        reference_image_url = None
        if "image" in media_types:
            from app.models.generated_content import GeneratedContent
            gc = session2.query(GeneratedContent).filter_by(id=_uuid.UUID(content_id)).first()
            if gc:
                idea = (gc.content_ideas or [])[idea_index] if idea_index < len(gc.content_ideas or []) else None
                cluster_index = idea.get("cluster_index") if idea else None
                if cluster_index is not None and 0 <= cluster_index < len(gc.clusters or []):
                    reference_image_url = gc.clusters[cluster_index].get("reference_image_url")

        for mt in media_types:
            prompt_text = prompts.get(mt, "")
            row = GeneratedMedia(
                generated_content_id=_uuid.UUID(content_id),
                idea_index=idea_index,
                media_type=mt,
                provider=_PROVIDER_MAP[mt],
                status="pending",
                prompt=prompt_text,
            )
            session2.add(row)
            session2.flush()
            created_ids.append(str(row.id))
            background_tasks.add_task(
                run_generation,
                row_id=str(row.id),
                media_type=mt,
                prompt=prompt_text,
                user_id=user_id,
                content_id=content_id,
                idea_index=idea_index,
                reference_image_url=reference_image_url if mt == "image" else None,
            )
        session2.commit()
    except HTTPException:
        raise
    except Exception as e:
        session2.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session2.close()

    return {"status": "queued", "media_ids": created_ids}


@app.get("/api/generate-media/{generated_content_id}")
def list_generated_media(generated_content_id: str, idea_index: Optional[int] = None):
    """Poll endpoint — returns all generated_media rows for a content digest."""
    from app.db import SessionLocal
    from app.models.generated_media import GeneratedMedia
    import uuid as _uuid

    session = SessionLocal()
    try:
        q = session.query(GeneratedMedia).filter_by(
            generated_content_id=_uuid.UUID(generated_content_id)
        )
        if idea_index is not None:
            q = q.filter_by(idea_index=idea_index)
        rows = q.order_by(GeneratedMedia.created_at.desc()).all()
        return [
            {
                "id": str(r.id),
                "idea_index": r.idea_index,
                "media_type": r.media_type,
                "provider": r.provider,
                "status": r.status,
                "asset_url": r.asset_url,
                "duration_seconds": float(r.duration_seconds) if r.duration_seconds else None,
                "cost_usd": float(r.cost_usd) if r.cost_usd else None,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Phase 1 — closed feedback loop: connected accounts (OAuth) + content posts
# (manual tracking, one-click publish, and the aggregate Performance feed)
# ---------------------------------------------------------------------------

_SOCIAL_PLATFORMS = {"youtube", "tiktok", "instagram", "twitter"}


def _get_social_provider(platform: str):
    if platform not in _SOCIAL_PLATFORMS:
        raise HTTPException(status_code=404, detail=f"Unsupported platform: {platform}")
    from app.social.service import _get_provider
    try:
        return _get_provider(platform)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/social/{platform}/connect")
def social_connect(platform: str, user_id: str, content_profile_id: Optional[str] = None):
    """Redirects to the platform's OAuth consent screen. `state` carries the
    user_id (and, when connecting a niche's own dedicated "avatar account",
    the content_profile_id to bind it to) through the round trip so the
    callback knows who's connecting and to which profile — this app has no
    server-side session of its own (auth lives in the frontend's Supabase
    session), so, consistent with every other endpoint here trusting a
    passed-in user_id (e.g. GET /users/{user_id}/content-profiles), it isn't
    cryptographically signed. Worst case of tampering is a connection landing
    on the wrong user_id/profile, not a security bypass of anything sensitive."""
    from fastapi.responses import RedirectResponse
    provider = _get_social_provider(platform)
    state = f"{user_id}:{content_profile_id or ''}"
    return RedirectResponse(provider.get_authorize_url(state=state))


@app.get("/api/social/{platform}/callback")
def social_callback(platform: str, code: Optional[str] = None, state: Optional[str] = None):
    from fastapi.responses import RedirectResponse
    from app.db import SessionLocal
    from app.models.connected_account import ConnectedAccount
    from app.social.crypto import encrypt
    import uuid as _uuid
    from datetime import datetime, timedelta

    frontend_base = os.getenv("NEXT_PUBLIC_SITE_URL", "https://culturix-web.vercel.app")

    if not code or not state:
        return RedirectResponse(f"{frontend_base}/settings?social_error=missing_code")

    provider = _get_social_provider(platform)
    try:
        result = provider.exchange_code(code)
    except Exception as e:
        logging.error("Social OAuth exchange failed (%s): %s", platform, e)
        return RedirectResponse(f"{frontend_base}/settings?social_error=exchange_failed")

    session = SessionLocal()
    try:
        try:
            # state = "{user_id}:{content_profile_id}" (content_profile_id may be
            # empty — a legacy/user-wide connect not bound to any one niche).
            # Split on the last ":" isn't needed since UUIDs never contain ":".
            raw_user_id, _, raw_profile_id = state.partition(":")
            user_id = _uuid.UUID(raw_user_id)
            content_profile_id = _uuid.UUID(raw_profile_id) if raw_profile_id else None

            # content_profile_id alone is enough to identify a profile-bound row
            # (it's globally unique per profile+platform, and a profile belongs
            # to exactly one user already); a legacy/unbound connect (None) isn't
            # unique on its own, so that case must also match on user_id — Postgres
            # doesn't dedupe multiple NULLs under the unique constraint, so without
            # this a lookup could otherwise land on a different user's legacy row.
            query = session.query(ConnectedAccount).filter_by(platform=platform)
            if content_profile_id is not None:
                query = query.filter_by(content_profile_id=content_profile_id)
            else:
                query = query.filter_by(user_id=user_id, content_profile_id=None)
            account = query.first()
            if not account:
                account = ConnectedAccount(user_id=user_id, platform=platform, content_profile_id=content_profile_id)
                session.add(account)
            account.access_token = encrypt(result.access_token)
            if result.refresh_token:
                account.refresh_token = encrypt(result.refresh_token)
            account.token_expires_at = (
                datetime.utcnow() + timedelta(seconds=result.expires_in_seconds)
                if result.expires_in_seconds else None
            )
            account.scopes = "readonly,upload" if platform == "youtube" else None
            account.platform_account_id = result.platform_account_id
            account.platform_username = result.platform_username
            account.status = "active"
            account.connected_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            # Covers a missing TOKEN_ENCRYPTION_KEY (encrypt() raises RuntimeError)
            # as well as any DB error — same clean-redirect contract as the
            # exchange_code failure above, not a raw 500 on a real OAuth callback.
            session.rollback()
            logging.error("Social OAuth callback failed to save connection (%s): %s", platform, e)
            return RedirectResponse(f"{frontend_base}/settings?social_error=save_failed")
    finally:
        session.close()

    return RedirectResponse(f"{frontend_base}/settings?connected={platform}")


@app.delete("/api/social/{platform}/disconnect")
def social_disconnect(platform: str, user_id: str, content_profile_id: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.connected_account import ConnectedAccount
    import uuid as _uuid

    session = SessionLocal()
    try:
        query = session.query(ConnectedAccount).filter_by(user_id=_uuid.UUID(user_id), platform=platform)
        query = query.filter_by(content_profile_id=_uuid.UUID(content_profile_id) if content_profile_id else None)
        account = query.first()
        if account:
            account.status = "revoked"  # soft — kept for audit, matches this codebase's status-not-delete pattern
            session.commit()
        return {"status": "disconnected"}
    finally:
        session.close()


@app.get("/api/social/accounts")
def list_connected_accounts(user_id: str, content_profile_id: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.connected_account import ConnectedAccount
    import uuid as _uuid

    session = SessionLocal()
    try:
        query = session.query(ConnectedAccount).filter_by(user_id=_uuid.UUID(user_id))
        if content_profile_id is not None:
            query = query.filter_by(content_profile_id=_uuid.UUID(content_profile_id))
        rows = query.all()
        return [
            {
                "platform": r.platform,
                "platform_username": r.platform_username,
                "status": r.status,
                "connected_at": r.connected_at.isoformat() if r.connected_at else None,
                "content_profile_id": str(r.content_profile_id) if r.content_profile_id else None,
            }
            for r in rows if r.status != "revoked"
        ]
    finally:
        session.close()


@app.post("/api/content-posts")
def create_content_post(body: dict, background_tasks: BackgroundTasks):
    """Manual tracking — user posted this idea themselves somewhere and is
    pasting the link. Still requires a connected account for that platform,
    since even read-only metric fetching needs a valid access token."""
    from app.db import SessionLocal
    from app.models.content_post import ContentPost
    from app.models.generated_content import GeneratedContent
    from app.social.service import fetch_and_record, resolve_active_account
    import uuid as _uuid
    from datetime import datetime, timedelta

    content_id = body.get("content_id")
    idea_index = body.get("idea_index")
    user_id = body.get("user_id")
    platform = body.get("platform")
    post_url = body.get("post_url")

    if not all([content_id, idea_index is not None, user_id, platform, post_url]):
        raise HTTPException(status_code=400, detail="content_id, idea_index, user_id, platform, post_url required")

    session = SessionLocal()
    try:
        content = session.query(GeneratedContent).filter_by(id=_uuid.UUID(content_id)).first()
        account = resolve_active_account(
            session, _uuid.UUID(user_id), platform,
            content_profile_id=content.content_profile_id if content else None,
        )
        if not account:
            raise HTTPException(
                status_code=400,
                detail=f"Connect your {platform} account in Settings before tracking a post."
            )

        post = ContentPost(
            generated_content_id=_uuid.UUID(content_id),
            idea_index=idea_index,
            user_id=_uuid.UUID(user_id),
            platform=platform,
            post_url=post_url,
            created_via="manual",
            status="pending",
            tracking_until=datetime.utcnow() + timedelta(days=14),
        )
        session.add(post)
        session.commit()
        background_tasks.add_task(fetch_and_record, content_post_id=str(post.id))
        return {"status": "queued", "content_post_id": str(post.id)}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/content-posts/publish")
def publish_content_post(body: dict, background_tasks: BackgroundTasks):
    """One-click / autonomous publish — Culturix posts the idea's finished
    video directly via the platform's API. No post_url from the caller; the
    platform tells us the post ID once it's live."""
    from app.db import SessionLocal
    from app.models.content_post import ContentPost
    from app.models.generated_content import GeneratedContent
    from app.models.generated_media import GeneratedMedia
    from app.social.service import publish_and_record, resolve_active_account
    import uuid as _uuid

    content_id = body.get("content_id")
    idea_index = body.get("idea_index")
    user_id = body.get("user_id")
    platform = body.get("platform")

    if not all([content_id, idea_index is not None, user_id, platform]):
        raise HTTPException(status_code=400, detail="content_id, idea_index, user_id, platform required")

    session = SessionLocal()
    try:
        content = session.query(GeneratedContent).filter_by(id=_uuid.UUID(content_id)).first()
        account = resolve_active_account(
            session, _uuid.UUID(user_id), platform,
            content_profile_id=content.content_profile_id if content else None,
        )
        if not account:
            raise HTTPException(
                status_code=400,
                detail=f"Connect your {platform} account in Settings before publishing."
            )

        media = session.query(GeneratedMedia).filter_by(
            generated_content_id=_uuid.UUID(content_id), idea_index=idea_index,
            media_type="video", status="done",
        ).first()
        if not media:
            raise HTTPException(status_code=400, detail="Generate a video for this idea before publishing.")

        post = ContentPost(
            generated_content_id=_uuid.UUID(content_id),
            idea_index=idea_index,
            user_id=_uuid.UUID(user_id),
            platform=platform,
            created_via="published",
            status="pending",
        )
        session.add(post)
        session.commit()
        background_tasks.add_task(publish_and_record, content_post_id=str(post.id))
        return {"status": "queued", "content_post_id": str(post.id)}
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.get("/api/content-posts/{generated_content_id}")
def list_content_posts(generated_content_id: str, idea_index: Optional[int] = None):
    """Poll endpoint — same shape as GET /api/generate-media/{id}, used by
    both the manual-tracking and publish frontend flows."""
    from app.db import SessionLocal
    from app.models.content_post import ContentPost
    import uuid as _uuid

    session = SessionLocal()
    try:
        q = session.query(ContentPost).filter_by(generated_content_id=_uuid.UUID(generated_content_id))
        if idea_index is not None:
            q = q.filter_by(idea_index=idea_index)
        rows = q.order_by(ContentPost.created_at.desc()).all()
        return [_serialize_content_post(r) for r in rows]
    finally:
        session.close()


@app.post("/api/content-posts/{content_post_id}/refresh")
def refresh_content_post(content_post_id: str, background_tasks: BackgroundTasks):
    from app.social.service import fetch_and_record
    background_tasks.add_task(fetch_and_record, content_post_id=content_post_id)
    return {"status": "queued"}


@app.get("/api/content-posts")
def list_all_content_posts(user_id: str):
    """Aggregate feed for the Performance page — every tracked/published post
    across all of a user's content profiles, latest metrics, views desc."""
    from app.db import SessionLocal
    from app.models.content_post import ContentPost
    from app.models.generated_content import GeneratedContent
    import uuid as _uuid

    session = SessionLocal()
    try:
        rows = (
            session.query(ContentPost)
            .filter_by(user_id=_uuid.UUID(user_id))
            .order_by(ContentPost.latest_views.desc().nullslast())
            .all()
        )
        content_ids = {r.generated_content_id for r in rows}
        contents = {
            c.id: c for c in session.query(GeneratedContent).filter(GeneratedContent.id.in_(content_ids)).all()
        } if content_ids else {}

        out = []
        for r in rows:
            data = _serialize_content_post(r)
            content = contents.get(r.generated_content_id)
            idea = (content.content_ideas or [])[r.idea_index] if content and content.content_ideas else {}
            data["hook"] = idea.get("hook")
            out.append(data)
        return out
    finally:
        session.close()


def _serialize_content_post(r) -> dict:
    return {
        "id": str(r.id),
        "generated_content_id": str(r.generated_content_id),
        "idea_index": r.idea_index,
        "platform": r.platform,
        "post_url": r.post_url,
        "created_via": r.created_via,
        "status": r.status,
        "latest_views": r.latest_views,
        "latest_likes": r.latest_likes,
        "latest_comments": r.latest_comments,
        "latest_shares": r.latest_shares,
        "last_fetched_at": r.last_fetched_at.isoformat() if r.last_fetched_at else None,
        "error": r.error,
        "posted_at": r.posted_at.isoformat() if r.posted_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@app.post("/api/webhooks/delivery")
def webhook_delivery():
    import threading
    def _run():
        try:
            from app.pipeline.graph import run_pipeline
            run_pipeline()
        except Exception as e:
            logging.error("Webhook pipeline failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@app.post("/api/webhooks/high-velocity-trend")
def high_velocity_trend_webhook(body: dict):
    """
    Receiver for scraping/culturix_scraping/hooks.py's trigger_content_engine —
    fires when the velocity pipeline sees an item cross VELOCITY_THRESHOLD.

    Deliberately just records the alert rather than triggering run_pipeline():
    this fires automatically and potentially repeatedly (a burst of trending
    items = a burst of webhook calls), and run_pipeline() makes real DeepSeek/
    Claude calls and would email real users if RESEND_API_KEY is ever set in
    production — not something that should happen unattended on every hit.
    Surfacing these via /admin/high-velocity-alerts is the safer default;
    wiring one of these into an actual pipeline run is a deliberate decision
    to make later, not a side effect of this endpoint existing.
    """
    from app.db import SessionLocal
    from app.models.high_velocity_alert import HighVelocityAlert
    from datetime import datetime as _dt

    posted_at = None
    raw_created_at = body.get("created_at")
    if raw_created_at:
        try:
            posted_at = _dt.fromisoformat(str(raw_created_at).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            posted_at = None

    session = SessionLocal()
    try:
        alert = HighVelocityAlert(
            platform=body.get("platform", "unknown"),
            external_id=str(body.get("video_id", "")),
            description=body.get("description"),
            velocity_score=float(body.get("velocity_score") or 0),
            like_count=body.get("like_count"),
            view_count=body.get("view_count"),
            trend_posted_at=posted_at,
        )
        session.add(alert)
        session.commit()
        logging.info("High-velocity trend alert recorded: platform=%s id=%s score=%s",
                     alert.platform, alert.external_id, alert.velocity_score)
        return {"status": "recorded", "id": alert.id}
    except Exception as e:
        session.rollback()
        logging.error("Failed to record high-velocity alert: %s", e)
        raise HTTPException(status_code=500, detail="Failed to record alert")
    finally:
        session.close()


# ── Workstream 2 — New Collectors ─────────────────────────────────────────────

@app.post("/collect/xhs")
def collect_xhs(keywords: list[str] | None = None):
    from app.collectors.xiaohongshu import store_xhs_signals
    return {"inserted": store_xhs_signals(keywords)}


@app.post("/collect/all")
def collect_all():
    from app.collectors.orchestrator import run_all_collectors
    return run_all_collectors()


# ── Admin endpoints (superadmin only — caller must verify identity) ────────────

@app.get("/admin/trends")
def trends_recent(limit: int = 200, platform: Optional[str] = None, search: Optional[str] = None):
    from app.db import SessionLocal
    from app.models.trend import Trend
    session = SessionLocal()
    try:
        q = session.query(Trend).order_by(Trend.collected_at.desc())
        if platform:
            q = q.filter(Trend.platform == platform)
        if search:
            q = q.filter(Trend.content.ilike(f"%{search}%"))
        trends = q.limit(limit).all()
        return [
            {
                "id": t.id, "platform": t.platform, "content": (t.content or "")[:200],
                "author": t.author, "url": t.url, "likes": t.likes,
                "comments": t.comments, "language": t.language,
                "collected_at": t.collected_at.isoformat() if t.collected_at else None,
            }
            for t in trends
        ]
    finally:
        session.close()


@app.get("/api/trends")
def trends_recent(limit: int = 20):
    """Public, user-facing view of active trend clusters with momentum —
    the real, persisted, incrementally-tracked clusters (not the ephemeral
    per-digest snapshot in generated_content.clusters, which has no
    momentum and can be empty for any given digest)."""
    from app.db import SessionLocal
    from app.models.cluster import Cluster
    session = SessionLocal()
    try:
        clusters = (
            session.query(Cluster)
            .order_by(Cluster.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": c.id,
                "theme": c.theme,
                "summary": c.summary,
                "size": c.size,
                "momentum": c.momentum,
                "previous_size": c.previous_size,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in clusters
        ]
    finally:
        session.close()


@app.get("/admin/clusters")
def clusters_recent(limit: int = 50):
    """
    trend_count is computed live (COUNT of trends actually pointing at this
    cluster) rather than trusting Cluster.size — that stored column can go
    stale relative to the live trends.cluster_id state (clustering_service.py's
    reuse path doesn't always keep it in sync, under investigation separately),
    which showed up as the admin UI listing "N trends" on a cluster whose
    detail view then showed none. Computing it live here means the number
    shown always matches what the detail endpoint will actually return,
    regardless of the underlying staleness cause.
    """
    from app.db import SessionLocal
    from app.models.cluster import Cluster
    from app.models.trend import Trend
    import sqlalchemy as sa
    session = SessionLocal()
    try:
        clusters = session.query(Cluster).order_by(Cluster.created_at.desc()).limit(limit).all()
        counts = dict(
            session.query(Trend.cluster_id, sa.func.count(Trend.id))
            .filter(Trend.cluster_id.in_([c.id for c in clusters]))
            .group_by(Trend.cluster_id)
            .all()
        )
        return [
            {
                "id": c.id, "label": c.label, "description": c.theme,
                "trend_count": counts.get(c.id, 0), "created_at": c.created_at.isoformat() if c.created_at else None,
                "momentum": c.momentum,  # "up" | "down" | "neutral" | null (no prior baseline yet)
                "previous_size": c.previous_size,
            }
            for c in clusters
        ]
    finally:
        session.close()


@app.get("/admin/content-check-log")
def content_check_log_recent(limit: int = 100):
    from app.db import SessionLocal
    from app.models.content_check_log import ContentCheckLog
    session = SessionLocal()
    try:
        rows = session.query(ContentCheckLog).order_by(ContentCheckLog.checked_at.desc()).limit(limit).all()
        return [
            {
                "id": str(r.id),
                "generated_content_id": str(r.generated_content_id),
                "idea_index": r.idea_index,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
                "previous_score": r.previous_score,
                "new_score": r.new_score,
                "trend_score": r.trend_score,
                "freshness_score": r.freshness_score,
                "persona_score": r.persona_score,
                "previous_status": r.previous_status,
                "new_status": r.new_status,
                "action_taken": r.action_taken,
            }
            for r in rows
        ]
    finally:
        session.close()


@app.get("/admin/trend-validation-log")
def trend_validation_log_recent(limit: int = 100):
    from app.db import SessionLocal
    from app.models.trend_validation_log import TrendValidationLog
    session = SessionLocal()
    try:
        rows = session.query(TrendValidationLog).order_by(TrendValidationLog.checked_at.desc()).limit(limit).all()
        return [
            {
                "id": str(r.id),
                "source": r.source,
                "subject": r.subject,
                "legitimate": r.legitimate,
                "safe": r.safe,
                "durability": r.durability,
                "status": r.status,
                "reason": r.reason,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            }
            for r in rows
        ]
    finally:
        session.close()


@app.get("/admin/trend-history")
def trend_history_recent(limit: int = 100):
    from app.db import SessionLocal
    from app.models.trend_theme import TrendTheme
    session = SessionLocal()
    try:
        rows = (
            session.query(TrendTheme)
            .order_by(TrendTheme.last_seen_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": t.id,
                "canonical_name": t.canonical_name,
                "description": t.description,
                "emotional_theme": t.emotional_theme,
                "first_seen_at": t.first_seen_at.isoformat() if t.first_seen_at else None,
                "last_seen_at": t.last_seen_at.isoformat() if t.last_seen_at else None,
                "occurrence_count": t.occurrence_count,
                "recurrence_pattern": t.recurrence_pattern,
                "dominant_day_of_week": t.dominant_day_of_week,
                "pattern_confidence": t.pattern_confidence,
            }
            for t in rows
        ]
    finally:
        session.close()


@app.get("/admin/trend-history/{theme_id}/occurrences")
def trend_history_occurrences(theme_id: int, limit: int = 200):
    from app.db import SessionLocal
    from app.models.trend_occurrence import TrendOccurrence
    session = SessionLocal()
    try:
        rows = (
            session.query(TrendOccurrence)
            .filter(TrendOccurrence.theme_id == theme_id)
            .order_by(TrendOccurrence.occurrence_date.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": o.id,
                "occurrence_date": o.occurrence_date.isoformat() if o.occurrence_date else None,
                "day_of_week": o.day_of_week,
                "name_snapshot": o.name_snapshot,
                "description_snapshot": o.description_snapshot,
                "size": o.size,
                "durability": o.durability,
            }
            for o in rows
        ]
    finally:
        session.close()


@app.get("/admin/high-velocity-alerts")
def high_velocity_alerts_recent(limit: int = 100):
    from app.db import SessionLocal
    from app.models.high_velocity_alert import HighVelocityAlert
    session = SessionLocal()
    try:
        rows = (
            session.query(HighVelocityAlert)
            .order_by(HighVelocityAlert.received_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": a.id,
                "platform": a.platform,
                "external_id": a.external_id,
                "description": a.description,
                "velocity_score": a.velocity_score,
                "like_count": a.like_count,
                "view_count": a.view_count,
                "trend_posted_at": a.trend_posted_at.isoformat() if a.trend_posted_at else None,
                "received_at": a.received_at.isoformat() if a.received_at else None,
            }
            for a in rows
        ]
    finally:
        session.close()


@app.get("/admin/personas")
def personas_recent(limit: int = 50):
    from app.db import SessionLocal
    from app.models.persona import Persona
    session = SessionLocal()
    try:
        personas = session.query(Persona).order_by(Persona.created_at.desc()).limit(limit).all()
        import json as _json
        def _split(v):
            if not v:
                return []
            try:
                parsed = _json.loads(v)
                return parsed if isinstance(parsed, list) else [str(parsed)]
            except Exception:
                return [s.strip() for s in v.split(",") if s.strip()]
        return [
            {
                "id": p.id, "name": p.name, "description": p.description,
                "motivations": _split(p.motivations),
                "interests": _split(p.interests),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in personas
        ]
    finally:
        session.close()


@app.get("/admin/digests")
def admin_digests(limit: int = 20):
    from app.db import SessionLocal
    from app.models.generated_content import GeneratedContent
    session = SessionLocal()
    try:
        digests = (
            session.query(GeneratedContent)
            .order_by(GeneratedContent.generated_at.desc().nullslast())
            .limit(limit).all()
        )
        return [
            {
                "id": str(d.id), "user_id": str(d.user_id),
                "generated_at": d.generated_at.isoformat() if d.generated_at else None,
                "trend_date": str(d.trend_date),
                "cluster_count": len(d.clusters) if d.clusters else 0,
                "idea_count": len(d.content_ideas) if d.content_ideas else 0,
                "delivered": d.delivered,
            }
            for d in digests
        ]
    finally:
        session.close()


@app.get("/admin/stats")
def admin_stats():
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.models.cluster import Cluster
    from app.models.persona import Persona
    from app.models.user_profile import UserProfile
    from app.models.generated_content import GeneratedContent
    import sqlalchemy as sa
    session = SessionLocal()
    try:
        platforms = session.execute(
            sa.text("SELECT platform, COUNT(*) as n FROM trends GROUP BY platform ORDER BY n DESC")
        ).fetchall()
        return {
            "total_trends": session.query(Trend).count(),
            "total_clusters": session.query(Cluster).count(),
            "total_personas": session.query(Persona).count(),
            "total_users": session.query(UserProfile).count(),
            "total_digests": session.query(GeneratedContent).count(),
            "by_platform": {row[0]: row[1] for row in platforms},
        }
    finally:
        session.close()


@app.get("/admin/integration-health")
def get_integration_health():
    """Latest health-check result per integration — see
    app/integration_health.py. Checked daily by the scheduler; use
    POST /admin/integration-health/check-now for an on-demand check."""
    from app.db import SessionLocal
    from app.models.integration_health import IntegrationHealth
    import sqlalchemy as sa

    session = SessionLocal()
    try:
        subq = (
            session.query(
                IntegrationHealth.integration_name,
                sa.func.max(IntegrationHealth.checked_at).label("max_checked"),
            )
            .group_by(IntegrationHealth.integration_name)
            .subquery()
        )
        rows = (
            session.query(IntegrationHealth)
            .join(
                subq,
                sa.and_(
                    IntegrationHealth.integration_name == subq.c.integration_name,
                    IntegrationHealth.checked_at == subq.c.max_checked,
                ),
            )
            .all()
        )
        return [
            {
                "integration": r.integration_name,
                "status": r.status,
                "error": r.error,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            }
            for r in rows
        ]
    finally:
        session.close()


@app.post("/admin/integration-health/check-now")
def check_integration_health_now():
    from app.integration_health import run_all_health_checks
    return run_all_health_checks()


@app.post("/admin/collect")
def admin_collect():
    """
    Was hardcoded to just YouTube (4 regions) + Twitter-via-proxy (3 regions)
    — silently skipping Reddit, TikTok, Xiaohongshu, Pinterest, Wikipedia,
    and Bluesky, and never using the Apify-preferred Twitter path even when
    APIFY_API_TOKEN is set. Delegates to the same run_all_collectors() the
    scheduler and POST /collect/all already use, so "Collect now" actually
    means all sources, not a stale partial subset.
    """
    import threading
    def _run():
        try:
            from app.collectors.orchestrator import run_all_collectors
            results = run_all_collectors()
            logging.info("Admin collect results: %s", results)
        except Exception as e:
            logging.error("Admin collect failed: %s", e)
    threading.Thread(target=_run, daemon=True).start()
    return {"status": "collecting"}


# ── User approval endpoints ────────────────────────────────────────────────────

@app.get("/admin/users")
def admin_users():
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile
    from app.models.content_profile import ContentProfile
    session = SessionLocal()
    try:
        users = session.query(UserProfile).order_by(UserProfile.created_at.asc()).all()
        result = []
        for u in users:
            profiles = (
                session.query(ContentProfile)
                .filter_by(user_id=u.user_id)
                .order_by(ContentProfile.created_at.asc())
                .all()
            )
            result.append({
                "id": str(u.id),
                "user_id": str(u.user_id),
                "approved": u.approved,
                "plan": u.plan or "free",
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "content_profiles": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "industry_niche": p.industry_niche,
                        "target_platforms": p.target_platforms or [],
                        "is_active": p.is_active,
                        "created_at": p.created_at.isoformat() if p.created_at else None,
                    }
                    for p in profiles
                ],
            })
        return result
    finally:
        session.close()


@app.post("/admin/users/{user_id}/approve")
def approve_user(user_id: str):
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile
    import uuid as _uuid
    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        profile.approved = True
        session.commit()
        return {"status": "approved", "user_id": user_id}
    finally:
        session.close()


@app.post("/admin/users/{user_id}/reject")
def reject_user(user_id: str):
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile
    import uuid as _uuid
    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        profile.approved = False
        session.commit()
        return {"status": "rejected", "user_id": user_id}
    finally:
        session.close()


@app.get("/api/users/{user_id}/approved")
def check_user_approved(user_id: str):
    """Called by the frontend to gate dashboard access."""
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile
    import uuid as _uuid
    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
        # No profile yet (hasn't completed onboarding) → let them through to onboarding
        if not profile:
            return {"approved": True, "has_profile": False}
        return {"approved": profile.approved, "has_profile": True, "plan": profile.plan or "free"}
    finally:
        session.close()


# ── Billing (Stripe) ───────────────────────────────────────────────────────────

@app.post("/api/billing/create-checkout-session")
def billing_create_checkout_session(body: dict):
    user_id = body.get("user_id")
    email = body.get("email")
    base_url = body.get("base_url") or os.getenv("NEXT_PUBLIC_SITE_URL", "https://culturix-web.vercel.app")
    if not user_id or not email:
        raise HTTPException(status_code=400, detail="user_id and email required")

    if not os.getenv("STRIPE_SECRET_KEY") or not os.getenv("STRIPE_PRICE_ID_PRO"):
        raise HTTPException(status_code=503, detail="Billing not configured — add STRIPE_SECRET_KEY and STRIPE_PRICE_ID_PRO to Railway env vars")

    from app.billing import create_checkout_session
    try:
        url = create_checkout_session(user_id, email, base_url)
        return {"url": url}
    except Exception as e:
        logging.error("Checkout session creation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/billing/create-portal-session")
def billing_create_portal_session(body: dict):
    user_id = body.get("user_id")
    base_url = body.get("base_url") or os.getenv("NEXT_PUBLIC_SITE_URL", "https://culturix-web.vercel.app")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    if not os.getenv("STRIPE_SECRET_KEY"):
        raise HTTPException(status_code=503, detail="Billing not configured — add STRIPE_SECRET_KEY to Railway env vars")

    from app.billing import create_portal_session
    try:
        url = create_portal_session(user_id, base_url)
        return {"url": url}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logging.error("Portal session creation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/webhooks/stripe")
async def billing_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not os.getenv("STRIPE_WEBHOOK_SECRET"):
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET not configured")

    from app.billing import handle_webhook_event
    try:
        result = handle_webhook_event(payload, sig_header)
        logging.info("Stripe webhook handled: %s", result)
        return {"status": "ok", **result}
    except Exception as e:
        logging.error("Stripe webhook verification/handling failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/admin/users/{user_id}/plan")
def set_user_plan(user_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.user_profile import UserProfile
    import uuid as _uuid
    plan = body.get("plan", "free")
    if plan not in ("free", "pro"):
        raise HTTPException(status_code=400, detail="plan must be 'free' or 'pro'")
    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(user_id=_uuid.UUID(user_id)).first()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")
        profile.plan = plan
        session.commit()
        return {"status": "updated", "user_id": user_id, "plan": plan}
    finally:
        session.close()


# ── Content profiles (per-user, multi-niche) ──────────────────────────────────

PLAN_PROFILE_LIMITS = {"free": 1, "pro": 10}


@app.get("/users/{user_id}/content-profiles")
def list_content_profiles(user_id: str):
    from app.db import SessionLocal
    from app.models.content_profile import ContentProfile
    import uuid as _uuid
    session = SessionLocal()
    try:
        profiles = (
            session.query(ContentProfile)
            .filter_by(user_id=_uuid.UUID(user_id))
            .order_by(ContentProfile.created_at.asc())
            .all()
        )
        return [_serialize_cp(p) for p in profiles]
    finally:
        session.close()


@app.post("/users/{user_id}/content-profiles")
def create_content_profile(user_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.content_profile import ContentProfile
    from app.models.user_profile import UserProfile
    import uuid as _uuid
    session = SessionLocal()
    try:
        uid = _uuid.UUID(user_id)
        _superadmin_id = os.getenv("SUPERADMIN_USER_ID", "")
        if user_id != _superadmin_id:
            user = session.query(UserProfile).filter_by(user_id=uid).first()
            plan = (user.plan or "free") if user else "free"
            limit = PLAN_PROFILE_LIMITS.get(plan, 1)
            existing = session.query(ContentProfile).filter_by(user_id=uid).count()
            if existing >= limit:
                raise HTTPException(
                    status_code=403,
                    detail=f"Your {plan} plan allows {limit} content profile(s). Upgrade to add more."
                )
        cp = ContentProfile(
            user_id=uid,
            name=body.get("name", "New Profile"),
            industry_niche=body.get("industry_niche"),
            target_platforms=body.get("target_platforms", []),
            target_regions=body.get("target_regions", []),
            content_goals=body.get("content_goals", []),
            content_tones=body.get("content_tones", []),
            persona_tags=body.get("persona_tags", []),
            target_age_min=body.get("target_age_min", 18),
            target_age_max=body.get("target_age_max", 35),
            delivery_freq=body.get("delivery_freq", "daily"),
            delivery_time=body.get("delivery_time", "07:00"),
            delivery_day_of_week=body.get("delivery_day_of_week", 0),
            preferred_formats=body.get("preferred_formats", []),
        )
        session.add(cp)
        session.commit()
        session.refresh(cp)
        return _serialize_cp(cp)
    finally:
        session.close()


@app.put("/users/{user_id}/content-profiles/{profile_id}")
def update_content_profile(user_id: str, profile_id: str, body: dict):
    from app.db import SessionLocal
    from app.models.content_profile import ContentProfile
    import uuid as _uuid
    session = SessionLocal()
    try:
        cp = session.query(ContentProfile).filter_by(
            id=_uuid.UUID(profile_id), user_id=_uuid.UUID(user_id)
        ).first()
        if not cp:
            raise HTTPException(status_code=404, detail="Profile not found")
        for field in ("name", "industry_niche", "target_platforms", "target_regions",
                      "content_goals", "content_tones", "persona_tags",
                      "target_age_min", "target_age_max", "delivery_freq", "delivery_time",
                      "delivery_day_of_week", "is_active", "publish_mode", "preferred_formats"):
            if field in body:
                setattr(cp, field, body[field])
        session.commit()
        session.refresh(cp)
        return _serialize_cp(cp)
    finally:
        session.close()


@app.post("/users/{user_id}/content-profiles/{profile_id}/account-suggestions")
def get_account_suggestions(user_id: str, profile_id: str):
    """Ephemeral, regenerate-on-demand suggestions for a NEW dedicated social
    account (platform fit + name/handle ideas) for this profile's niche —
    helps the user decide what account to go create before connecting one.
    Nothing here is persisted; a fresh call always regenerates."""
    from app.db import SessionLocal
    from app.models.content_profile import ContentProfile
    from app.account_suggestions import generate_account_suggestions
    import uuid as _uuid

    session = SessionLocal()
    try:
        cp = session.query(ContentProfile).filter_by(
            id=_uuid.UUID(profile_id), user_id=_uuid.UUID(user_id)
        ).first()
        if not cp:
            raise HTTPException(status_code=404, detail="Profile not found")

        profile_dict = {
            "industry_niche": cp.industry_niche,
            "target_platforms": cp.target_platforms or [],
            "content_goals": cp.content_goals or [],
            "content_tones": cp.content_tones or [],
            "persona_tags": cp.persona_tags or [],
        }
        try:
            return generate_account_suggestions(profile_dict)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Suggestion generation failed: {e}")
    except HTTPException:
        raise
    finally:
        session.close()


@app.delete("/users/{user_id}/content-profiles/{profile_id}")
def delete_content_profile(user_id: str, profile_id: str):
    from app.db import SessionLocal
    from app.models.content_profile import ContentProfile
    import uuid as _uuid
    session = SessionLocal()
    try:
        cp = session.query(ContentProfile).filter_by(
            id=_uuid.UUID(profile_id), user_id=_uuid.UUID(user_id)
        ).first()
        if not cp:
            raise HTTPException(status_code=404, detail="Profile not found")
        session.delete(cp)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


def _serialize_cp(p) -> dict:
    return {
        "id": str(p.id),
        "user_id": str(p.user_id),
        "name": p.name,
        "industry_niche": p.industry_niche,
        "target_platforms": p.target_platforms or [],
        "target_regions": p.target_regions or [],
        "content_goals": p.content_goals or [],
        "content_tones": p.content_tones or [],
        "persona_tags": p.persona_tags or [],
        "target_age_min": p.target_age_min,
        "target_age_max": p.target_age_max,
        "delivery_freq": p.delivery_freq,
        "delivery_time": p.delivery_time,
        "delivery_day_of_week": p.delivery_day_of_week,
        "is_active": p.is_active,
        "publish_mode": p.publish_mode,
        "preferred_formats": p.preferred_formats or [],
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
