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

import sqlalchemy as sa
from anthropic import Anthropic
from dotenv import load_dotenv

from app.db import SessionLocal
from app.models.trend import Trend
from app.models.cluster import Cluster
from app.clustering_hdbscan import cluster_embeddings_hdbscan

load_dotenv()
_anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Arbitrary fixed key for a Postgres session-level advisory lock — see the
# lock acquisition in run_clustering() for why this exists.
_CLUSTERING_ADVISORY_LOCK_KEY = 918_273_645


def _fingerprint(trends: list) -> str:
    ids = sorted(str(t.id) for t in trends)
    return hashlib.sha256(",".join(ids).encode()).hexdigest()


def _jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# Size change beyond this fraction counts as real momentum, not just noise
# from the rolling most-recent-N-trends window shifting slightly run to run.
_MOMENTUM_THRESHOLD = 0.15
# Below this overlap with a prior cluster, treat it as a genuinely new topic
# rather than a continuation (no momentum to report — no prior baseline).
_MOMENTUM_MIN_OVERLAP = 0.3


def _compute_momentum(new_ids: set, old_cluster_members: dict, existing_by_id: dict):
    """Finds the best-overlapping prior cluster for this run's group and
    compares sizes to derive 'up' | 'down' | 'neutral' | None (no match)."""
    best_id, best_overlap = None, 0.0
    for old_id, old_ids in old_cluster_members.items():
        score = _jaccard(new_ids, old_ids)
        if score > best_overlap:
            best_id, best_overlap = old_id, score

    if best_id is None or best_overlap < _MOMENTUM_MIN_OVERLAP or best_id not in existing_by_id:
        return None, None

    previous_size = existing_by_id[best_id].size or 0
    current_size = len(new_ids)
    if previous_size == 0:
        return None, previous_size

    change = (current_size - previous_size) / previous_size
    if change > _MOMENTUM_THRESHOLD:
        momentum = "up"
    elif change < -_MOMENTUM_THRESHOLD:
        momentum = "down"
    else:
        momentum = "neutral"
    return momentum, previous_size


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
    """
    Postgres session-level advisory lock guards the whole read-modify-write
    cycle below. Found while investigating clusters that showed a nonzero
    trend count but zero trends actually pointing at them: this function
    reads all existing clusters, clears cluster_id for its working set,
    reassigns/creates/deletes clusters, then commits — all as multiple
    separate statements, not one atomic transaction-level guarantee against
    a second concurrent run doing the same over the same trend rows. Several
    manual pipeline triggers fired close together (this session's testing)
    plausibly overlapped with each other or the scheduler, each one's
    clear-and-reassign racing the other's, leaving orphaned Cluster rows
    whose members got reassigned elsewhere mid-flight. The lock makes a
    second concurrent call skip immediately instead of racing.
    """
    session = SessionLocal()
    got_lock = False
    try:
        got_lock = bool(session.execute(
            sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": _CLUSTERING_ADVISORY_LOCK_KEY}
        ).scalar())
        if not got_lock:
            return {
                "clusters": 0,
                "noise": 0,
                "total_trends": 0,
                "skipped": "another run_clustering() call is already in progress",
            }

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
        existing_by_id = {c.id: c for c in all_existing_clusters}

        # Capture each trend's PRIOR cluster membership before we reset it
        # below — this is the baseline "momentum" comparisons are made
        # against, so it has to be read before any assignment happens.
        old_cluster_members: dict = {}
        for t in trends:
            if t.cluster_id is not None:
                old_cluster_members.setdefault(t.cluster_id, set()).add(t.id)

        # Clear cluster_id for this working set — assigned per-object rather
        # than a bulk .update(synchronize_session=False), deliberately. A
        # bulk update executes raw SQL without updating these already-loaded
        # objects' ORM-tracked "original" value, so when a trend is later
        # reassigned back to the SAME cluster it already had before this run
        # (the common steady-state case), `trend.cluster_id = existing.id`
        # looks like a no-op to SQLAlchemy's dirty-checking — comparing
        # against the pre-clear in-memory value, not the just-nulled DB row —
        # and gets silently skipped at flush, leaving the row NULL from this
        # clear forever. This was the actual cause of clusters showing a
        # nonzero trend count with zero trends actually pointing at them:
        # confirmed by re-running twice in a row — the second run reused
        # every cluster unchanged and mismatches roughly quintupled.
        for t in trends:
            t.cluster_id = None

        surviving_ids = set()
        reused = 0
        created = 0
        for label, cluster_trends in sorted(label_map.items()):
            fp = _fingerprint(cluster_trends)
            new_ids = {t.id for t in cluster_trends}
            momentum, previous_size = _compute_momentum(new_ids, old_cluster_members, existing_by_id)
            existing = existing_by_fp.get(fp)

            if existing:
                for trend in cluster_trends:
                    trend.cluster_id = existing.id
                # size was previously only set at creation, never on reuse —
                # left it stale indefinitely, which also silently corrupted
                # _compute_momentum's baseline (reads existing.size) for any
                # cluster reused more than once.
                existing.size = len(cluster_trends)
                existing.updated_at = datetime.utcnow()
                # An exact fingerprint match compares identical membership
                # against itself, so this naturally comes out "neutral".
                existing.momentum = momentum
                existing.previous_size = previous_size
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
                momentum=momentum,
                previous_size=previous_size,
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
        if got_lock:
            try:
                session.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": _CLUSTERING_ADVISORY_LOCK_KEY})
                session.commit()
            except Exception:
                pass  # connection may already be broken; Postgres releases session-level advisory locks on disconnect regardless
        session.close()
