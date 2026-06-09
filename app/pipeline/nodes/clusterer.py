"""
Agent 2 — Trend Clusterer
Embeds signals with Voyage AI, stores in Qdrant, asks DeepSeek to identify clusters.
"""
import json
import logging
import os
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.clusterer")


def _get_deepseek():
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )


def _embed_signals(texts: list[str]) -> list[list[float]]:
    import voyageai
    client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    all_embeddings = []
    batch_size = 20
    import time
    for i in range(0, len(texts), batch_size):
        chunk = texts[i: i + batch_size]
        for attempt in range(3):
            try:
                result = client.embed(chunk, model="voyage-3", input_type="document")
                all_embeddings.extend(result.embeddings)
                if i + batch_size < len(texts):
                    time.sleep(1)
                break
            except Exception as e:
                if "rate" in str(e).lower() and attempt < 2:
                    time.sleep(22)
                else:
                    raise
    return all_embeddings


def _store_in_qdrant(signals: list[dict], embeddings: list[list[float]]):
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_key = os.getenv("QDRANT_API_KEY")
    if not qdrant_url:
        logger.warning("QDRANT_URL not set — skipping Qdrant storage")
        return

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct, OptimizersConfigDiff

        qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_key)

        # Create collection if it doesn't exist
        collections = [c.name for c in qdrant.get_collections().collections]
        if "culturix_signals" not in collections:
            qdrant.create_collection(
                collection_name="culturix_signals",
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )

        points = [
            PointStruct(
                id=abs(hash(s.get("external_id") or str(i))) % (2**63),
                vector=emb,
                payload={
                    "source": s.get("platform") or s.get("source", ""),
                    "text": s.get("translated_content") or s.get("content_text") or "",
                    "likes": s.get("likes") or 0,
                    "collected_at": str(s.get("collected_at") or ""),
                },
            )
            for i, (s, emb) in enumerate(zip(signals, embeddings))
        ]
        qdrant.upsert(collection_name="culturix_signals", points=points)
        logger.info("Stored %d vectors in Qdrant", len(points))
    except Exception as e:
        logger.error("Qdrant storage failed: %s", e)


def cluster_trends(state: PipelineState) -> PipelineState:
    signals = state["raw_signals"]
    if not signals:
        logger.warning("No signals to cluster")
        state["clusters"] = []
        return state

    texts = [s.get("translated_content") or s.get("content_text") or s.get("title") or "" for s in signals]
    texts = [t for t in texts if t.strip()]

    logger.info("Embedding %d signals...", len(texts))
    try:
        embeddings = _embed_signals(texts)
        state["embeddings"] = embeddings
        _store_in_qdrant(signals, embeddings)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        state["embeddings"] = []
        state["errors"] = state.get("errors", []) + [f"embedding: {e}"]

    # Ask DeepSeek to identify clusters
    sample = texts[:200]
    prompt = f"""Analyze these {len(sample)} social media posts from across TikTok, YouTube, Twitter, Xiaohongshu, and Reddit.

Identify the top 10-15 distinct cultural trends or narratives emerging right now.

For each trend return a JSON object with these exact keys:
- name: short trend name (3-6 words)
- description: 1-2 sentence description
- emotional_theme: the core emotion driving this trend (e.g. "anxiety", "aspiration", "humor")
- example_posts: array of 3 verbatim example posts from the input
- viral_signals: what makes this spread (e.g. "relatability", "FOMO", "shock value")
- why_it_matters: why a brand should care (1 sentence)

Return ONLY a valid JSON array with no other text, markdown, or explanation.

Posts:
{json.dumps(sample)}"""

    try:
        deepseek = _get_deepseek()
        response = deepseek.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        state["clusters"] = json.loads(raw)
        logger.info("Identified %d clusters", len(state["clusters"]))
    except Exception as e:
        logger.error("DeepSeek clustering failed: %s", e)
        state["clusters"] = []
        state["errors"] = state.get("errors", []) + [f"clustering: {e}"]

    return state
