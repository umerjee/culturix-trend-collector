"""Semantic relevance ranking of trend-engine Personas/Clusters against a
CultureToons brand's own stated trend_interests. Before this existed, the
Scripts tab's "Suggest a script from a trend" picker showed the exact same
unfiltered global trend feed to every brand regardless of what it actually
posts (a comedy-cartoon account seeing "August 2026 solar eclipse" and
"Wikipedia navigation pages" next to anything genuinely usable).

Reuses the same Voyage.ai embedding infra character-memory retrieval
already depends on (app/embeddings.py) — fail-open by the same convention
used there: an embedding failure just means this call can't be
personalized this time, not a broken page.

Rate-limit aware: Voyage's free tier is 3 requests/minute, so embeddings
are never recomputed live for every candidate on every page load. Each
Persona/Cluster's embedding is computed once and cached on the row itself
(relevance_embedding); a given request only embeds candidates that don't
have one yet, capped at _MAX_NEW_EMBEDDINGS_PER_REQUEST so worst-case
latency stays bounded — the cache fills in across a few requests rather
than all at once."""
import logging
from math import sqrt

logger = logging.getLogger("culturix.services.culturetoon_trend_relevance")

_MAX_NEW_EMBEDDINGS_PER_REQUEST = 15


def _cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_interests_embedding(brand) -> list:
    """Returns brand.trend_interests_embedding, computing+caching it first
    if missing (update_brand clears the cached value whenever
    trend_interests text changes, so a stale cache never lingers). Mutates
    `brand` in place; the caller owns the session commit. Raises whatever
    the embedding call raises — the one caller (get_trend_sources) treats
    that as "can't personalize this request", not a hard failure."""
    if brand.trend_interests_embedding:
        return brand.trend_interests_embedding
    from app.embeddings import embed_text
    vector = embed_text(brand.trend_interests)
    brand.trend_interests_embedding = vector
    return vector


def rank_by_relevance(session, candidates: list, text_fn, interests_embedding: list) -> list:
    """candidates: already-loaded ORM rows (Persona or Cluster instances),
    each with a relevance_embedding column. text_fn: candidate -> str, the
    text to embed for whichever candidates don't have one cached yet.
    Returns candidates sorted by similarity to interests_embedding,
    descending. Candidates that couldn't be embedded this request (over
    the per-request cap, or a failed call) are appended at the end,
    unranked rather than dropped, so nothing silently disappears from the
    picker just because its embedding hasn't been computed yet."""
    from app.embeddings import embed_batch

    to_embed = [c for c in candidates if not c.relevance_embedding][:_MAX_NEW_EMBEDDINGS_PER_REQUEST]
    if to_embed:
        try:
            vectors = embed_batch([text_fn(c) for c in to_embed])
            for c, v in zip(to_embed, vectors):
                c.relevance_embedding = v
            session.flush()
        except Exception:
            logger.warning("Embedding %d trend candidates failed, continuing without ranking them", len(to_embed), exc_info=True)

    scored, unscored = [], []
    for c in candidates:
        if c.relevance_embedding:
            scored.append((c, _cosine_similarity(c.relevance_embedding, interests_embedding)))
        else:
            unscored.append(c)
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, _ in scored] + unscored
