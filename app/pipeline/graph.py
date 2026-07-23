"""
LangGraph pipeline — daily orchestrator. Runs collection→digest end to end:
translate_signals → load_signals → embed_signals → cluster_and_persist →
cluster_trends → validate_clusters → map_trend_history → map_persona_tags →
map_personas → generate_content → validate_ideas → write_digests

cluster_and_persist keeps the admin-facing Cluster table populated (HDBSCAN);
cluster_trends/map_personas use Voyage+Qdrant+DeepSeek for the actual
content-generation matching — two intentionally separate clustering paths,
not unreconciled duplication (audited 2026-07-22, the admin-facing Cluster
table is real, actively-rendered UI in AdminDashboard.tsx, not dead code).
validate_clusters/validate_ideas are the AI legitimacy/safety/durability gate
that reviews proposed trends and generated ideas before they can influence
or reach users — see app/pipeline/nodes/trend_validator.py.
map_trend_history persists each run's approved clusters into a durable,
cross-day trend history (TrendTheme/TrendOccurrence) and attaches recurrence
context (weekly/yearly/sustained/spike, dominant day-of-week) back onto each
cluster for content_strategist and trend_validator to consult — see
app/pipeline/nodes/trend_historian.py.
map_persona_tags (added 2026-07-23) tracks recurring audience-persona
archetypes the same way — centroid-match, occurrence log, momentum — and
supersedes the old generate_personas node/app/personas.py's
generate_clustered_personas, which kept a *separate*, disconnected
per-cluster Persona table with no recurrence or momentum tracking at all.
That old generation path is intentionally superseded, not merely
duplicative — see app/pipeline/nodes/persona_tag_tracker.py's module
docstring. (The 2026-07-22 audit above concluded "keep both" for the
*clustering* paths, which still stands; it did not evaluate persona
*generation* specifically, which this entry now supersedes.)

Usage:
    python -m app.pipeline.graph
"""
import logging
from app.pipeline.state import PipelineState
from app.pipeline.nodes.translator import translate_signals
from app.pipeline.nodes.embedder import embed_signals
from app.pipeline.nodes.legacy_cluster import cluster_and_persist
from app.pipeline.nodes.clusterer import cluster_trends
from app.pipeline.nodes.trend_validator import validate_clusters, validate_ideas
from app.pipeline.nodes.trend_historian import map_trend_history
from app.pipeline.nodes.persona_tag_tracker import map_persona_tags
from app.pipeline.nodes.persona_mapper import map_personas
from app.pipeline.nodes.content_strategist import generate_content
from app.pipeline.nodes.digest_writer import write_digests

logger = logging.getLogger("culturix.pipeline")


def load_signals(state: PipelineState) -> PipelineState:
    from app.db import SessionLocal
    from app.models.trend import Trend
    import sqlalchemy as sa
    import uuid as _uuid

    session = SessionLocal()
    try:
        trends = (
            session.query(Trend)
            .filter(Trend.translated_content.isnot(None))
            .order_by(Trend.collected_at.desc())
            .limit(500)
            .all()
        )
        state["raw_signals"] = [
            {
                "id": t.id,
                "platform": t.platform,
                "external_id": t.external_id,
                "translated_content": t.translated_content or t.content or t.title or "",
                "title": t.title,
                "likes": t.likes or 0,
                "collected_at": str(t.collected_at),
                "region": t.region,
                "image_url": t.image_url,
            }
            for t in trends
        ]
        logger.info("Loaded %d signals", len(state["raw_signals"]))

        # Load active content profiles for approved users
        try:
            result = session.execute(sa.text("""
                SELECT
                    cp.id            AS content_profile_id,
                    cp.user_id,
                    cp.name,
                    cp.industry_niche,
                    cp.target_platforms,
                    cp.target_regions,
                    cp.content_goals,
                    cp.content_tones,
                    cp.persona_tags,
                    cp.target_age_min,
                    cp.target_age_max,
                    cp.delivery_freq,
                    cp.delivery_time
                FROM content_profiles cp
                JOIN user_profiles up ON up.user_id = cp.user_id
                WHERE cp.is_active = TRUE AND up.approved = TRUE
                LIMIT 500
            """))
            rows = result.mappings().all()
            # Stringify UUIDs so downstream dicts stay JSON-safe
            state["user_profiles"] = [
                {k: (str(v) if isinstance(v, _uuid.UUID) else v) for k, v in dict(r).items()}
                for r in rows
            ]
            logger.info("Loaded %d content profiles", len(state["user_profiles"]))
        except Exception as e:
            logger.warning("Could not load content profiles: %s", e)
            state["user_profiles"] = []

    finally:
        session.close()

    return state


def build_pipeline():
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        logger.error("langgraph not installed — run: pip install langgraph")
        raise

    graph = StateGraph(PipelineState)
    graph.add_node("load_signals", load_signals)
    graph.add_node("translate_signals", translate_signals)
    graph.add_node("embed_signals", embed_signals)
    graph.add_node("cluster_and_persist", cluster_and_persist)
    graph.add_node("cluster_trends", cluster_trends)
    graph.add_node("validate_clusters", validate_clusters)
    graph.add_node("map_trend_history", map_trend_history)
    graph.add_node("map_persona_tags", map_persona_tags)
    graph.add_node("map_personas", map_personas)
    graph.add_node("generate_content", generate_content)
    graph.add_node("validate_ideas", validate_ideas)
    graph.add_node("write_digests", write_digests)

    graph.set_entry_point("translate_signals")
    graph.add_edge("translate_signals", "load_signals")
    graph.add_edge("load_signals", "embed_signals")
    graph.add_edge("embed_signals", "cluster_and_persist")
    graph.add_edge("cluster_and_persist", "cluster_trends")
    graph.add_edge("cluster_trends", "validate_clusters")
    graph.add_edge("validate_clusters", "map_trend_history")
    graph.add_edge("map_trend_history", "map_persona_tags")
    graph.add_edge("map_persona_tags", "map_personas")
    graph.add_edge("map_personas", "generate_content")
    graph.add_edge("generate_content", "validate_ideas")
    graph.add_edge("validate_ideas", "write_digests")
    graph.add_edge("write_digests", END)

    return graph.compile()


def run_pipeline() -> PipelineState:
    logging.basicConfig(level=logging.INFO)
    pipeline = build_pipeline()
    initial: PipelineState = {
        "raw_signals": [],
        "user_profiles": [],
        "embeddings": [],
        "clusters": [],
        "persona_matches": [],
        "generated_content": [],
        "errors": [],
    }
    return pipeline.invoke(initial)


if __name__ == "__main__":
    result = run_pipeline()
    print(f"Pipeline complete.")
    print(f"  Clusters identified: {len(result.get('clusters', []))}")
    print(f"  Users processed: {len(result.get('generated_content', []))}")
    print(f"  Errors: {result.get('errors', [])}")
