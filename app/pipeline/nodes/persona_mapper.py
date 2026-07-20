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


def _embed_clusters_as_documents(clusters: list[dict]) -> list[list[float]]:
    """input_type='document' (not 'query', which _embed_query uses for the
    profile side) — Voyage's models are trained for this asymmetric
    query/document pairing, so mismatching input_type on either side would
    make the cosine similarities below meaningless."""
    import voyageai
    client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    texts = [f"{c.get('name', '')}. {c.get('description', '')}".strip() for c in clusters]
    result = client.embed(texts, model="voyage-3", input_type="document")
    return result.embeddings


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _rank_clusters_by_relevance(clusters: list[dict], query_vec: list[float], top_n: int = 8) -> list[dict]:
    """Ranks clusters by embedding similarity to the profile's niche/tags/
    platforms query instead of the previous unconditional clusters[:8] —
    every profile was getting the identical top-8 regardless of niche, which
    is how e.g. a Beauty & Self-Care profile ended up with FIFA World Cup
    clusters in its digest. Fails open to the old slice-based behavior if
    embedding fails for any reason, consistent with the rest of this
    pipeline's fail-open philosophy."""
    if not clusters or not query_vec:
        return clusters[:top_n]
    try:
        cluster_vecs = _embed_clusters_as_documents(clusters)
    except Exception as e:
        logger.warning("Cluster relevance embedding failed, falling back to unranked slice: %s", e)
        return clusters[:top_n]

    scored = sorted(
        zip(clusters, cluster_vecs),
        key=lambda pair: _cosine_similarity(query_vec, pair[1]),
        reverse=True,
    )
    return [c for c, _ in scored[:top_n]]


def _search_qdrant(query_vec: list[float], limit: int = 20) -> list[dict]:
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_key = os.getenv("QDRANT_API_KEY")
    if not qdrant_url:
        return []
    try:
        from qdrant_client import QdrantClient, models
        qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_key)
        # qdrant-client >=1.8 uses query_points; fall back to search for older versions
        try:
            results = qdrant.query_points(
                collection_name="culturix_signals",
                query=query_vec,
                limit=limit,
            ).points
        except AttributeError:
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

        query_vec = None
        try:
            query_vec = _embed_query(query_text)
            top_signals = _search_qdrant(query_vec, limit=20)
        except Exception as e:
            logger.error("Embedding query failed for user %s: %s", profile.get("user_id"), e)
            top_signals = []

        relevant_clusters = _rank_clusters_by_relevance(clusters, query_vec)

        matches.append({
            "user_id": profile["user_id"],
            "profile": profile,
            "clusters": relevant_clusters,
            "top_signals": top_signals[:10],
        })

    state["persona_matches"] = matches
    logger.info("Mapped %d user profiles to clusters", len(matches))
    return state
