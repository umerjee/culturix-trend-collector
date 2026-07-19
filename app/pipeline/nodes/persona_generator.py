"""
Generate Personas — thin LangGraph wrapper around the existing cluster-aware
persona generator. Keeps Persona/TrendPersona populated for the admin dashboard.
"""
import logging
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.persona_generator")


def generate_personas(state: PipelineState) -> PipelineState:
    try:
        from app.personas import generate_clustered_personas
        result = generate_clustered_personas(limit=200, min_cluster_size=5)
        logger.info("Persona generation done: %s", result)
    except Exception as e:
        logger.error("Persona generation failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"persona_gen: {e}"]

    return state
