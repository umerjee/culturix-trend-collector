"""Character memory storage + semantic retrieval for CultureToons — see
docs/culturix-comedy-architecture.md §3.5 and §7 Phase 4.

Reuses the trend engine's existing Voyage.ai embedding client
(app/embeddings.py) and Qdrant instance (same QDRANT_URL/QDRANT_API_KEY env
vars already used by app/pipeline/nodes/clusterer.py), in a dedicated
"culturetoon_memories" collection so it never collides with the trend
engine's own "culturix_signals" collection. Fail-open by design, matching
this codebase's existing Qdrant-storage convention (_store_in_qdrant in
clusterer.py): if Qdrant is unreachable, memory rows still save to Postgres
(the durable source of truth) and retrieval just returns nothing rather
than blocking script generation on a vector-store outage.
"""
import logging
import os

logger = logging.getLogger("culturix.services.culturetoon_memory")

_COLLECTION = "culturetoon_memories"
_VECTOR_SIZE = 1024  # matches voyage-3's output dimension, same as clusterer.py's collection


def _get_qdrant():
    qdrant_url = os.getenv("QDRANT_URL")
    if not qdrant_url:
        return None
    from qdrant_client import QdrantClient
    return QdrantClient(url=qdrant_url, api_key=os.getenv("QDRANT_API_KEY"))


def _ensure_collection(qdrant) -> None:
    from qdrant_client.models import Distance, VectorParams
    collections = [c.name for c in qdrant.get_collections().collections]
    if _COLLECTION not in collections:
        qdrant.create_collection(
            collection_name=_COLLECTION,
            vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
        )


def index_memory(memory) -> None:
    """Embeds memory.content and upserts it into Qdrant, payload-tagged with
    character_variant_id/brand_id for filtered retrieval. Best-effort — logs
    and returns on any failure rather than raising, since the memory is
    already durably saved in Postgres by the time this is called."""
    try:
        qdrant = _get_qdrant()
        if not qdrant:
            logger.warning("QDRANT_URL not set — memory %s not indexed for retrieval", memory.id)
            return
        from app.embeddings import embed_text
        from qdrant_client.models import PointStruct

        vector = embed_text(memory.content)
        _ensure_collection(qdrant)
        qdrant.upsert(collection_name=_COLLECTION, points=[
            PointStruct(
                id=str(memory.id),
                vector=vector,
                payload={
                    "character_variant_id": str(memory.character_variant_id),
                    "brand_id": str(memory.brand_id),
                    "memory_type": memory.memory_type,
                    "content": memory.content,
                },
            )
        ])
    except Exception:
        logger.warning("Failed to index memory %s for retrieval", memory.id, exc_info=True)


def delete_memory_index(memory_id) -> None:
    try:
        qdrant = _get_qdrant()
        if not qdrant:
            return
        qdrant.delete(collection_name=_COLLECTION, points_selector=[str(memory_id)])
    except Exception:
        logger.warning("Failed to remove memory %s from the retrieval index", memory_id, exc_info=True)


def retrieve_relevant_memories(variant_ids: list, query_text: str, top_k: int = 3) -> list:
    """Returns up to top_k memory content strings, semantically relevant to
    query_text, scoped to the given CharacterVariant ids — for script
    generation to inject into the prompt. Returns [] (not an error) if
    Qdrant isn't configured, the collection doesn't exist yet, or the call
    fails for any reason — a vector-store outage must not block script
    generation, just make it slightly less informed."""
    if not variant_ids or not query_text.strip():
        return []
    try:
        qdrant = _get_qdrant()
        if not qdrant:
            return []
        collections = [c.name for c in qdrant.get_collections().collections]
        if _COLLECTION not in collections:
            return []

        from app.embeddings import embed_text
        from qdrant_client.models import Filter, FieldCondition, MatchAny

        vector = embed_text(query_text)
        results = qdrant.search(
            collection_name=_COLLECTION,
            query_vector=vector,
            query_filter=Filter(must=[
                FieldCondition(key="character_variant_id", match=MatchAny(any=[str(v) for v in variant_ids])),
            ]),
            limit=top_k,
        )
        return [r.payload["content"] for r in results if r.payload and r.payload.get("content")]
    except Exception:
        logger.warning("Memory retrieval failed, continuing without memory context", exc_info=True)
        return []
