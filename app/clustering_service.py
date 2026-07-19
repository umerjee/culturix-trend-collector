"""
Standalone clustering service.

Runs HDBSCAN on stored trend embeddings, writes Cluster rows with
AI-generated theme + summary, and stamps cluster_id back onto each Trend.

Incremental: a cluster whose trend membership exactly matches a previous
run (same fingerprint) is reused as-is — no AI relabeling call. Only new
or changed clusters get a fresh AI label, and clusters whose membership
no longer appears in the current run are removed.
"""
import hashlib
import os
import json
from datetime import datetime

from anthropic import Anthropic
from dotenv import load_dotenv

from app.db import SessionLocal
from app.models.trend import Trend
from app.models.cluster import Cluster
from app.clustering_hdbscan import cluster_embeddings_hdbscan

load_dotenv()
_anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _fingerprint(trends: list) -> str:
    ids = sorted(str(t.id) for t in trends)
    return hashlib.sha256(",".join(ids).encode()).hexdigest()


def _ai_label_cluster(trends: list) -> dict:
    sample = "\n".join(
        f"- [{t.platform}] {t.title or t.content[:80]}"
        for t in trends[:15]
    )
    prompt = f"""You are a trend analyst. Given these trending social media posts grouped together by semantic similarity, identify the common theme.

Posts:
{sample}

Return ONLY valid JSON with:
- theme (string — 3-6 words, e.g. "AI in everyday life")
- summary (string — 1-2 sentences explaining what this cluster is about)"""

    response = _anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip("```json").strip("```").strip()
        return json.loads(cleaned)


def run_clustering(limit: int = 500, min_cluster_size: int = 5) -> dict:
    session = SessionLocal()
    try:
        trends = (
            session.query(Trend)
            .filter(Trend.embedding.isnot(None))
            .order_by(Trend.id.desc())
            .limit(limit)
            .all()
        )

        if len(trends) < min_cluster_size:
            return {
                "clusters": 0,
                "noise": 0,
                "total_trends": len(trends),
                "warning": f"Need at least {min_cluster_size} embedded trends to cluster.",
            }

        embeddings = [t.embedding for t in trends]
        labels = cluster_embeddings_hdbscan(embeddings, min_cluster_size=min_cluster_size)

        label_map: dict = {}
        for trend, label in zip(trends, labels):
            label_map.setdefault(int(label), []).append(trend)

        noise_count = len(label_map.pop(-1, []))

        all_existing_clusters = session.query(Cluster).all()
        existing_by_fp = {c.fingerprint: c for c in all_existing_clusters if c.fingerprint}

        # Clear cluster_id for this working set (cheap SQL); reassigned below
        # for whatever groups survive clustering this run, reused or new.
        session.query(Trend).filter(Trend.id.in_([t.id for t in trends])).update(
            {"cluster_id": None}, synchronize_session=False
        )

        surviving_ids = set()
        reused = 0
        created = 0
        for label, cluster_trends in sorted(label_map.items()):
            fp = _fingerprint(cluster_trends)
            existing = existing_by_fp.get(fp)

            if existing:
                for trend in cluster_trends:
                    trend.cluster_id = existing.id
                surviving_ids.add(existing.id)
                reused += 1
                continue

            ai_label = _ai_label_cluster(cluster_trends)
            cluster = Cluster(
                label=label,
                theme=ai_label.get("theme"),
                summary=ai_label.get("summary"),
                size=len(cluster_trends),
                fingerprint=fp,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(cluster)
            session.flush()

            for trend in cluster_trends:
                trend.cluster_id = cluster.id
            surviving_ids.add(cluster.id)
            created += 1

        # Anything not reused or freshly created this run is stale — including
        # clusters from before this fingerprint feature existed (no fingerprint
        # at all), which can never be matched and would otherwise never be
        # cleaned up.
        stale = [c for c in all_existing_clusters if c.id not in surviving_ids]
        for c in stale:
            session.delete(c)

        session.commit()
        return {
            "clusters": created + reused,
            "clusters_created": created,
            "clusters_reused": reused,
            "clusters_removed": len(stale),
            "noise": noise_count,
            "total_trends": len(trends),
        }

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
