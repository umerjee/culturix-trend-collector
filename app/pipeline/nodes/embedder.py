"""
Embed Signals — thin LangGraph wrapper around the existing Voyage embedding processor.
Populates Trend.embedding for any rows that don't have one yet.
"""
import logging
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.embedder")


def embed_signals(state: PipelineState) -> PipelineState:
    try:
        from app.embedding_processor import process_embeddings
        n = process_embeddings(limit=1000)
        logger.info("Embedded %d new trends", n)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"embed: {e}"]

    return state
