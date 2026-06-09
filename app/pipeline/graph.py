"""
LangGraph pipeline — full Tier 4 digest generation.
Runs: load_signals → cluster_trends → map_personas → generate_content → write_digests

Usage:
    python -m app.pipeline.graph
"""
import logging
from app.pipeline.state import PipelineState
from app.pipeline.nodes.clusterer import cluster_trends
from app.pipeline.nodes.persona_mapper import map_personas
from app.pipeline.nodes.content_strategist import generate_content
from app.pipeline.nodes.digest_writer import write_digests

logger = logging.getLogger("culturix.pipeline")


def load_signals(state: PipelineState) -> PipelineState:
    from app.db import SessionLocal
    from app.models.trend import Trend
    import sqlalchemy as sa

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
            }
            for t in trends
        ]
        logger.info("Loaded %d signals", len(state["raw_signals"]))
    finally:
        session.close()

    # Load active user profiles
    try:
        result = session.execute(sa.text("SELECT * FROM user_profiles LIMIT 500"))
        rows = result.mappings().all()
        state["user_profiles"] = [dict(r) for r in rows]
        logger.info("Loaded %d user profiles", len(state["user_profiles"]))
    except Exception as e:
        logger.warning("Could not load user profiles (table may not exist yet): %s", e)
        state["user_profiles"] = []

    return state


def build_pipeline():
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        logger.error("langgraph not installed — run: pip install langgraph")
        raise

    graph = StateGraph(PipelineState)
    graph.add_node("load_signals", load_signals)
    graph.add_node("cluster_trends", cluster_trends)
    graph.add_node("map_personas", map_personas)
    graph.add_node("generate_content", generate_content)
    graph.add_node("write_digests", write_digests)

    graph.set_entry_point("load_signals")
    graph.add_edge("load_signals", "cluster_trends")
    graph.add_edge("cluster_trends", "map_personas")
    graph.add_edge("map_personas", "generate_content")
    graph.add_edge("generate_content", "write_digests")
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
