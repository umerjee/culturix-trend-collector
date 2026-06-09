"""
Agent 3 — Persona Mapper
Matches trend clusters to user profiles using Voyage AI semantic search + Qdrant.
"""
import logging
import os
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.persona_mapper")


def _embed_query(text: str) -> list[float]:
    import voyageai
    client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    result = client.embed([text], model="voyage-3", input_type="query")
    return result.embeddings[0]


def _search_qdrant(query_vec: list[float], limit: int = 20) -> list[dict]:
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_key = os.getenv("QDRANT_API_KEY")
    if not qdrant_url:
        return []
    try:
        from qdrant_client import QdrantClient
        qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_key)
        results = qdrant.search(
            collection_name="culturix_signals",
            query_vector=query_vec,
            limit=limit,
        )
        return [r.payload for r in results]
    except Exception as e:
        logger.error("Qdrant search failed: %s", e)
        return []


def map_personas(state: PipelineState) -> PipelineState:
    clusters = state.get("clusters", [])
    profiles = state.get("user_profiles", [])

    if not profiles:
        logger.warning("No user profiles — skipping persona mapping")
        state["persona_matches"] = []
        return state

    matches = []
    for profile in profiles:
        niche = profile.get("industry_niche") or ""
        tags = " ".join(profile.get("persona_tags") or [])
        platforms = " ".join(profile.get("target_platforms") or [])
        query_text = f"{niche} {tags} {platforms}".strip() or "trending culture content"

        try:
            query_vec = _embed_query(query_text)
            top_signals = _search_qdrant(query_vec, limit=20)
        except Exception as e:
            logger.error("Embedding query failed for user %s: %s", profile.get("user_id"), e)
            top_signals = []

        # Score clusters by relevance to this user's profile
        # Simple heuristic: all clusters for now; can be refined with vector scoring
        relevant_clusters = clusters[:8]

        matches.append({
            "user_id": profile["user_id"],
            "profile": profile,
            "clusters": relevant_clusters,
            "top_signals": top_signals[:10],
        })

    state["persona_matches"] = matches
    logger.info("Mapped %d user profiles to clusters", len(matches))
    return state
