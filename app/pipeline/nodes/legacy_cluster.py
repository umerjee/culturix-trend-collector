"""
Cluster & Persist — thin LangGraph wrapper around the existing HDBSCAN clustering
service. Keeps the Cluster table and Trend.cluster_id populated so the admin
dashboard (/admin/clusters, /admin/stats) keeps working under the new orchestrator.
"""
import logging
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.legacy_cluster")


def cluster_and_persist(state: PipelineState) -> PipelineState:
    try:
        from app.clustering_service import run_clustering
        result = run_clustering(limit=1000, min_cluster_size=2)
        logger.info("Cluster persist done: %s", result)
    except Exception as e:
        logger.error("Cluster persist failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"cluster_persist: {e}"]

    return state
