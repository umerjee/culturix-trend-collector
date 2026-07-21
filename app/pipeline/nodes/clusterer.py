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


def _load_embeddings_by_id(ids: list) -> dict:
    """Reuse embeddings already computed by the embed_signals node (Trend.embedding)
    instead of re-embedding via Voyage — avoids a second, rate-limited API call
    on every pipeline run."""
    if not ids:
        return {}
    from app.db import SessionLocal
    from app.models.trend import Trend

    session = SessionLocal()
    try:
        rows = session.query(Trend.id, Trend.embedding).filter(Trend.id.in_(ids)).all()
        return {r.id: r.embedding for r in rows if r.embedding}
    finally:
        session.close()


def _call_cluster_llm(prompt: str) -> str:
    """DeepSeek first; falls back to Claude Haiku if DEEPSEEK_API_KEY is missing
    or the call fails, so a DeepSeek outage doesn't take down the whole daily run."""
    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            deepseek = _get_deepseek()
            response = deepseek.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("DeepSeek clustering failed, falling back to Claude: %s", e)

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


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

    logger.info("Loading precomputed embeddings for %d signals...", len(signals))
    embeddings_by_id = {}
    try:
        embeddings_by_id = _load_embeddings_by_id(
            [s["id"] for s in signals if s.get("id") is not None]
        )
    except Exception as e:
        logger.error("Loading embeddings failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"embedding: {e}"]

    embedded_signals = [s for s in signals if embeddings_by_id.get(s.get("id"))]
    embeddings = [embeddings_by_id[s["id"]] for s in embedded_signals]
    state["embeddings"] = embeddings
    if embedded_signals:
        _store_in_qdrant(embedded_signals, embeddings)
    else:
        logger.warning("No precomputed embeddings available — skipping Qdrant storage")

    # Ask DeepSeek (falls back to Claude) to identify clusters
    texts = [s.get("translated_content") or s.get("content_text") or s.get("title") or "" for s in signals]
    texts = [t for t in texts if t.strip()]
    sample = texts[:200]
    prompt = f"""Analyze these {len(sample)} social media posts from across TikTok, YouTube, Twitter, Xiaohongshu, and Reddit.

Identify the top 10-15 distinct cultural trends or narratives emerging right now.

For each trend return a JSON object with these exact keys:
- name: short trend name (3-6 words) — must name the actual specific real entity involved
  (the real person's name, the real movie/show/game title, the real event) wherever the
  posts identify one. "Celebrity Feud Drama" is not a usable name if the posts actually
  name who's feuding — use their names. Only fall back to a thematic label (no specific
  entity) if the posts genuinely don't name one (e.g. a broad format trend like "GRWM
  videos" with no single subject).
- description: 1-2 sentence description, same rule — name the real specific thing, not a paraphrase of it
- emotional_theme: the core emotion driving this trend (e.g. "anxiety", "aspiration", "humor")
- example_posts: array of 3 verbatim example posts from the input
- viral_signals: what makes this spread (e.g. "relatability", "FOMO", "shock value")
- why_it_matters: why a brand should care (1 sentence)

Return ONLY a valid JSON array with no other text, markdown, or explanation.

Posts:
{json.dumps(sample)}"""

    try:
        raw = _call_cluster_llm(prompt)
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        state["clusters"] = json.loads(raw)
        logger.info("Identified %d clusters", len(state["clusters"]))
    except Exception as e:
        logger.error("Clustering LLM failed: %s", e)
        state["clusters"] = []
        state["errors"] = state.get("errors", []) + [f"clustering: {e}"]

    return state
