import os
import json
from anthropic import Anthropic
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from app.db import SessionLocal
from app.models.cluster import Cluster
from app.models.trend import Trend
from app.models.persona import Persona
from app.models.trendpersona import TrendPersona

anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ── Claude helpers ────────────────────────────────────────────────────────────

def _call_claude(prompt: str, max_tokens: int = 600) -> str:
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _parse_json(raw: str) -> dict | list:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip().strip("```json").strip("```").strip()
        return json.loads(cleaned)


# ── AI functions ──────────────────────────────────────────────────────────────

def ai_infer_persona_from_posts(posts) -> dict:
    text = "\n\n".join(
        f"Title: {p.title}\nContent: {p.content}" for p in posts
    )
    prompt = f"""You are an expert in behavioral psychology and audience segmentation.

Infer the most likely persona behind the following social media posts.

Return ONLY valid JSON with these fields:
- name (string)
- description (string)
- motivations (string — comma-separated list)
- interests (string — comma-separated list)

Posts:
{text}"""
    return _parse_json(_call_claude(prompt))


def ai_generate_content_suggestions(persona: Persona, sample_posts) -> str:
    sample_text = "\n".join(
        f"- {p.title or p.content[:80]}" for p in sample_posts[:10]
    )
    prompt = f"""You are a creative content strategist.

Given the persona below and the trending posts they engage with, generate 5 specific, actionable content ideas tailored to this audience.

Persona: {persona.name}
Description: {persona.description}
Motivations: {persona.motivations}
Interests: {persona.interests}

Sample trending posts this persona engages with:
{sample_text}

Return ONLY valid JSON as a list of objects, each with:
- title (string — short, punchy content title)
- format (string — e.g. "short video", "carousel", "blog post", "poll")
- hook (string — one sentence that grabs attention)
- platform (string — best platform: YouTube, TikTok, Twitter, Reddit)"""
    raw = _call_claude(prompt, max_tokens=800)
    parsed = _parse_json(raw)
    return json.dumps(parsed, ensure_ascii=False)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _link_trends_to_persona(session, trends, persona):
    existing_ids = {
        row.trend_id
        for row in session.query(TrendPersona.trend_id)
        .filter(TrendPersona.persona_id == persona.id)
        .all()
    }
    for trend in trends:
        if trend.id not in existing_ids:
            session.add(TrendPersona(
                trend_id=trend.id,
                persona_id=persona.id,
                confidence=1.0,
            ))


# ── Public functions ──────────────────────────────────────────────────────────

def generate_personas_for_recent_trends(limit: int = 50) -> dict:
    """
    Single-persona mode: infer one persona from the most recent `limit` trends.
    Does not require clustering to have run first.
    """
    session = SessionLocal()
    try:
        trends = (
            session.query(Trend)
            .order_by(Trend.id.desc())
            .limit(limit)
            .all()
        )
        if not trends:
            return {"created_personas": 0, "assigned_links": 0}

        persona_data = ai_infer_persona_from_posts(trends)

        persona = session.query(Persona).filter(Persona.name == persona_data["name"]).first()
        created = 0
        if not persona:
            persona = Persona(
                name=persona_data["name"],
                description=persona_data["description"],
                motivations=persona_data.get("motivations"),
                interests=persona_data.get("interests"),
                created_at=datetime.utcnow(),
            )
            session.add(persona)
            session.flush()
            created = 1

        persona.content_suggestions = ai_generate_content_suggestions(persona, trends)
        _link_trends_to_persona(session, trends, persona)
        session.commit()
        return {"created_personas": created, "assigned_links": len(trends)}
    except Exception as e:
        session.rollback()
        return {"error": str(e)}
    finally:
        session.close()


def generate_clustered_personas(limit: int = 200, min_cluster_size: int = 5) -> dict:
    """
    Cluster-aware mode: reads existing Cluster rows written by clustering_service,
    generates one persona + content suggestions per cluster.

    Requires POST /process/cluster (or run_clustering()) to have run first.
    Skips clusters smaller than min_cluster_size (not worth a full persona), and
    caps the number of clusters processed to `limit`. Each cluster is committed
    independently so one bad AI response doesn't roll back the whole batch.
    """
    session = SessionLocal()
    try:
        all_clusters = session.query(Cluster).order_by(Cluster.id).all()

        if not all_clusters:
            return {
                "clusters": 0,
                "personas_created": 0,
                "warning": "No clusters found in DB. Run POST /process/cluster first.",
            }

        clusters = [c for c in all_clusters if (c.size or 0) >= min_cluster_size][:limit]

        already_covered = {
            cid for (cid,) in session.query(Persona.cluster_id)
            .filter(Persona.cluster_id.isnot(None))
            .all()
        }

        personas_created = 0
        skipped = 0
        failures = 0
        for cluster in clusters:
            if cluster.id in already_covered:
                skipped += 1
                continue

            posts = (
                session.query(Trend)
                .filter(Trend.cluster_id == cluster.id)
                .order_by(Trend.collected_at.desc())
                .limit(50)
                .all()
            )
            if not posts:
                continue

            try:
                persona_data = ai_infer_persona_from_posts(posts)
                persona = Persona(
                    name=persona_data["name"],
                    description=persona_data["description"],
                    motivations=persona_data.get("motivations"),
                    interests=persona_data.get("interests"),
                    cluster_id=cluster.id,
                    created_at=datetime.utcnow(),
                )
                session.add(persona)
                session.flush()

                persona.content_suggestions = ai_generate_content_suggestions(persona, posts)
                _link_trends_to_persona(session, posts, persona)
                session.commit()
                personas_created += 1
            except Exception:
                session.rollback()
                failures += 1

        return {
            "clusters": len(all_clusters),
            "eligible_clusters": len(clusters),
            "personas_created": personas_created,
            "skipped_existing": skipped,
            "failures": failures,
        }
    except Exception as e:
        session.rollback()
        return {"error": str(e)}
    finally:
        session.close()


def generate_suggestions_for_persona(persona_id: int) -> dict:
    """Regenerate content suggestions for an existing persona."""
    session = SessionLocal()
    try:
        persona = session.query(Persona).filter(Persona.id == persona_id).first()
        if not persona:
            return {"error": f"Persona {persona_id} not found"}

        trend_ids = [
            row.trend_id
            for row in session.query(TrendPersona.trend_id)
            .filter(TrendPersona.persona_id == persona_id)
            .all()
        ]
        posts = session.query(Trend).filter(Trend.id.in_(trend_ids)).limit(10).all()

        persona.content_suggestions = ai_generate_content_suggestions(persona, posts)
        session.commit()
        return {"persona_id": persona_id, "suggestions": json.loads(persona.content_suggestions)}
    except Exception as e:
        session.rollback()
        return {"error": str(e)}
    finally:
        session.close()
