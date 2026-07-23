"""
Generate Personas — thin LangGraph wrapper around app/personas.py's
cluster-aware persona generator.

SUPERSEDED as of 2026-07-23, no longer wired into graph.py — see
app/pipeline/nodes/persona_tag_tracker.py's module docstring for why. Kept
in place, not deleted, per this codebase's dormant-not-deleted convention
for superseded code; not called from anywhere live.
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
