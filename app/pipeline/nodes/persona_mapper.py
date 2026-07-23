"""
Agent 3 — Persona Mapper
Matches trend clusters to user profiles using Voyage AI semantic search + Qdrant.
"""
import logging
import os
from app.pipeline.state import PipelineState
from app.regions import REGION_LABEL_TO_CODES as _REGION_LABEL_TO_CODES

logger = logging.getLogger("culturix.pipeline.persona_mapper")


def _filter_by_region(clusters: list[dict], target_regions: list[str]) -> list[dict]:
    """Hard-filters clusters whose known regions don't overlap the profile's
    target_regions — this is what actually fixes a "target_regions: EU"
    profile getting an India-region trend (previously target_regions was
    captured at onboarding/settings but never consulted anywhere downstream).

    Fails open on unknown region data: a cluster with no resolvable regions
    (state['clusters'][i]['regions'] == [], set by clusterer.py's
    _tag_cluster_regions) is kept regardless — we have no basis to judge it
    either way, and excluding it would wrongly punish clusters built from
    regionless sources (Reddit, Wikipedia's en/es editions, Bluesky) that are
    legitimately global in nature, not mis-targeted.
    """
    if not target_regions or "Global" in target_regions:
        return clusters

    allowed_codes: set[str] = set()
    for label in target_regions:
        allowed_codes |= _REGION_LABEL_TO_CODES.get(label, set())
    if not allowed_codes:
        # None of the profile's labels map to anything we can filter on —
        # fail open rather than accidentally excluding everything.
        return clusters

    return [
        c for c in clusters
        if not c.get("regions") or set(c["regions"]) & allowed_codes
    ]


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

        # Region filter runs before relevance ranking so the top-N slice is
        # drawn from an already region-appropriate pool, rather than filtered
        # down after — the latter could otherwise leave fewer than top_n.
        region_filtered = _filter_by_region(clusters, profile.get("target_regions") or [])
        relevant_clusters = _rank_clusters_by_relevance(region_filtered, query_vec)

        matches.append({
            "user_id": profile["user_id"],
            "profile": profile,
            "clusters": relevant_clusters,
            "top_signals": top_signals[:10],
        })

    state["persona_matches"] = matches
    logger.info("Mapped %d user profiles to clusters", len(matches))
    return state
