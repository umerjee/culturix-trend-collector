"""
Persona Tag Tracker — the connected persona system. Matches each run's
approved clusters against a running catalog of recurring "persona
archetypes" (Cottagecore, Gen Z, Quiet Luxury, ...) the same way
trend_historian.py matches clusters to TrendThemes: embed, cosine-match
against a centroid, log an occurrence, let the centroid drift with a
weighted running average.

A cluster that doesn't match any known archetype seeds a brand-new,
AI-described Persona in "pending" status — not yet shown to users. Once an
archetype has recurred on 3+ distinct days it's promoted to "active" and
becomes selectable in the frontend picker (see GET /personas/active). One
that stops recurring gets flagged "dormant" so it quietly drops out of the
picker for new selections without deleting anything a profile has already
chosen. "active" personas also get a momentum classification (up/down/
neutral, same vocabulary as Cluster.momentum) so users targeting a
declining persona can be advised — see main.py's persona-advisory endpoint,
the Dashboard's PersonaAdvisory banner, and the digest email callout.

Supersedes app/personas.py's generate_clustered_personas as of 2026-07-23 —
that function and its LangGraph wrapper (persona_generator.py) are left in
place but no longer wired into graph.py, per this codebase's convention of
keeping superseded code dormant rather than deleting it.

Fail-open: if embedding or persistence fails, skip persona tracking for this
run and log a warning — this must never take down the daily pipeline.
"""
import logging
from collections import Counter
from datetime import date, datetime, timedelta

from app.pipeline.state import PipelineState
from app.pipeline.nodes._similarity import cosine_similarity, average_embedding

logger = logging.getLogger("culturix.pipeline.persona_tag_tracker")

_SIMILARITY_THRESHOLD = 0.85
_PROMOTION_MIN_OCCURRENCES = 3
_PENDING_EXPIRY_DAYS = 14
_DORMANT_AFTER_DAYS = 45
_MOMENTUM_WINDOW_DAYS = 14
_MOMENTUM_MIN_BASELINE = 2
_MOMENTUM_RISING_RATIO = 1.3
_MOMENTUM_DECLINING_RATIO = 0.6


def _cluster_text(cluster: dict) -> str:
    return f"{cluster.get('name', '')}. {cluster.get('description', '')}".strip()


def _infer_persona_from_cluster(cluster: dict) -> dict:
    """Mints a name/description/motivations/interests for a brand-new persona
    archetype, adapted from app/personas.py's ai_infer_persona_from_posts —
    fed this cluster's own name+description (what was actually embedded and
    matched on) instead of a separate raw-post fetch."""
    from app.personas import _call_claude, _parse_json

    prompt = f"""You are an expert in behavioral psychology and audience segmentation.

A recurring content/cultural trend has been detected:
Name: {cluster.get('name', '')}
Description: {cluster.get('description', '')}

Infer the audience persona/archetype most associated with this trend — the kind
of person who identifies with or engages with content like this (e.g. "Cottagecore",
"Gen Z", "Quiet Luxury" — a short, recognizable subculture/aesthetic label, not a
full sentence).

Return ONLY valid JSON with these fields:
- name (string — short, 1-4 words)
- description (string)
- motivations (string — comma-separated list)
- interests (string — comma-separated list)"""
    return _parse_json(_call_claude(prompt))


def _match_or_create_persona(session, personas: list, cluster: dict, vector: list, today: date):
    from app.models.persona import Persona
    from app.models.persona_occurrence import PersonaOccurrence

    best_persona, best_score = None, 0.0
    for persona in personas:
        score = cosine_similarity(persona.centroid_embedding or [], vector)
        if score > best_score:
            best_persona, best_score = persona, score

    if best_persona and best_score >= _SIMILARITY_THRESHOLD:
        persona = best_persona
        already_seen_today = (
            session.query(PersonaOccurrence)
            .filter(PersonaOccurrence.persona_id == persona.id, PersonaOccurrence.occurrence_date == today)
            .first()
        )
        if already_seen_today is None:
            session.add(PersonaOccurrence(
                persona_id=persona.id,
                cluster_id=cluster.get("db_cluster_id"),
                occurrence_date=today,
                day_of_week=today.weekday(),
            ))
            persona.centroid_embedding = average_embedding(
                persona.centroid_embedding, vector, persona.occurrence_count or 0
            )
            persona.occurrence_count = (persona.occurrence_count or 0) + 1
        persona.last_seen_at = datetime.utcnow()
        return persona

    persona_data = _infer_persona_from_cluster(cluster)
    persona = Persona(
        name=persona_data["name"],
        description=persona_data["description"],
        motivations=persona_data.get("motivations"),
        interests=persona_data.get("interests"),
        centroid_embedding=vector,
        status="pending",
        occurrence_count=1,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )
    session.add(persona)
    session.flush()  # assign persona.id for the occurrence FK below
    personas.append(persona)
    session.add(PersonaOccurrence(
        persona_id=persona.id,
        cluster_id=cluster.get("db_cluster_id"),
        occurrence_date=today,
        day_of_week=today.weekday(),
    ))
    return persona


def _recompute_status_and_momentum(session, persona) -> None:
    from app.models.persona_occurrence import PersonaOccurrence

    now = datetime.utcnow()

    if persona.status == "pending":
        if persona.occurrence_count >= _PROMOTION_MIN_OCCURRENCES:
            persona.status = "active"
        elif persona.first_seen_at and (now - persona.first_seen_at).days > _PENDING_EXPIRY_DAYS:
            # Never recurred enough to be a real archetype — a one-off, not
            # a pattern. Flagged dormant rather than deleted, same as every
            # other "superseded, not destroyed" convention in this codebase.
            persona.status = "dormant"
        return

    if persona.status == "active":
        if persona.last_seen_at and (now - persona.last_seen_at).days > _DORMANT_AFTER_DAYS:
            persona.status = "dormant"
            persona.momentum = None
            return

        cutoff_recent = now - timedelta(days=_MOMENTUM_WINDOW_DAYS)
        cutoff_prior = now - timedelta(days=_MOMENTUM_WINDOW_DAYS * 2)
        recent_count = (
            session.query(PersonaOccurrence)
            .filter(PersonaOccurrence.persona_id == persona.id, PersonaOccurrence.occurrence_date >= cutoff_recent.date())
            .count()
        )
        prior_count = (
            session.query(PersonaOccurrence)
            .filter(
                PersonaOccurrence.persona_id == persona.id,
                PersonaOccurrence.occurrence_date >= cutoff_prior.date(),
                PersonaOccurrence.occurrence_date < cutoff_recent.date(),
            )
            .count()
        )
        if prior_count < _MOMENTUM_MIN_BASELINE:
            persona.momentum = None
        elif recent_count >= prior_count * _MOMENTUM_RISING_RATIO:
            persona.momentum = "up"
        elif recent_count <= prior_count * _MOMENTUM_DECLINING_RATIO:
            persona.momentum = "down"
        else:
            persona.momentum = "neutral"


def map_persona_tags(state: PipelineState) -> PipelineState:
    clusters = state.get("clusters", [])
    if not clusters:
        return state

    from app.embeddings import embed_batch
    from app.db import SessionLocal
    from app.models.persona import Persona

    today = datetime.utcnow().date()
    session = SessionLocal()
    try:
        personas = session.query(Persona).filter(Persona.status.in_(("pending", "active"))).all()

        for cluster in clusters:
            try:
                vector = cluster.get("_embedding")
                if not vector:
                    vector = embed_batch([_cluster_text(cluster)])[0]
                if not vector:
                    continue
                _match_or_create_persona(session, personas, cluster, vector, today)
            except Exception as e:
                logger.warning("Persona tag mapping failed for cluster %r: %s", cluster.get("name"), e)
                state["errors"] = state.get("errors", []) + [f"persona_tag_tracker:{cluster.get('name')}:{e}"]
                continue

        for persona in personas:
            try:
                _recompute_status_and_momentum(session, persona)
            except Exception as e:
                logger.warning("Status/momentum recompute failed for persona %r: %s", persona.name, e)
                state["errors"] = state.get("errors", []) + [f"persona_tag_tracker:status:{persona.name}:{e}"]
                continue

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Persona tag tracking failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"persona_tag_tracker: {e}"]
    finally:
        session.close()

    return state
