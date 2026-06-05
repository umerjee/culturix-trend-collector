import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_):
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
        "https://culturix-trend-collector.vercel.app",
        "https://*.vercel.app",
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
    from app.collectors.twitter import store_twitter_trends, _get_bearer_from_env
    from app.collectors.twitter_fallback import store_twitter_trends_via_proxy

    if _get_bearer_from_env():
        try:
            inserted = store_twitter_trends(region)
            if inserted > 0:
                return {"inserted": inserted}
        except Exception as e:
            print(f"Twitter API failed: {e}, falling back to proxy")

    inserted = store_twitter_trends_via_proxy(region)
    if inserted > 0:
        return {"inserted": inserted, "source": "trends24.in proxy"}
    return {"inserted": 0, "warning": "Could not fetch Twitter trends from API or proxy fallback"}


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
