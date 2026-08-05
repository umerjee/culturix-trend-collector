"""
Standalone clustering service.

Runs HDBSCAN on stored trend embeddings, writes Cluster rows with
AI-generated theme + summary, and stamps cluster_id back onto each Trend.

Incremental: a cluster whose trend membership exactly matches a previous
run (same fingerprint) is reused as-is — no AI relabeling call. Only new
or changed clusters get a fresh AI label, and clusters whose membership
no longer appears in the current run are removed.

This is one of two clustering paths in this codebase — confirmed
intentional, not unreconciled duplication (audited 2026-07-22). This one
feeds the raw, persisted, admin-facing Cluster table (browsable via
/admin/clusters, rendered with momentum badges + drill-down detail in
AdminDashboard.tsx — a real, actively-used view). The other path,
app/pipeline/nodes/clusterer.py (Voyage+Qdrant+DeepSeek), feeds actual
content-generation matching and never persists to a table — its clusters
live only within one pipeline run's in-memory state. See app/personas.py's
module docstring for the fuller explanation. Don't merge or retire either
without checking what breaks: this one's momentum-over-time tracking has
no equivalent on the other path.
"""
import hashlib
import logging
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
logger = logging.getLogger("culturix.clustering_service")

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


def _ai_label_clusters_batch(clusters: list) -> dict:
    """clusters: [(label, trends), ...]. Returns {label: {"theme", "summary"}}
    for whichever clusters the model successfully labeled.

    One Anthropic call labels every cluster needing a fresh label this run,
    instead of one call per cluster — confirmed live that a run with ~66
    candidate clusters made 66 separate Haiku calls, which is both
    needlessly expensive for a non-interactive batch job and a much bigger
    blast radius when the account runs out of credit (one failed call used
    to mean one skipped cluster; now it's the same one call for everyone,
    same failure mode as before but 66x cheaper on a normal run). A cluster
    missing from the parsed response (model skipped it, malformed entry) is
    the caller's job to treat as failed — this still isolates one bad
    cluster from the rest of the batch's results, just at the parsing level
    instead of the API-call level."""
    if not clusters:
        return {}

    sections = []
    for label, trends in clusters:
        sample = "\n".join(f"- [{t.platform}] {t.title or t.content[:80]}" for t in trends[:8])
        sections.append(f'Cluster "{label}":\n{sample}')

    prompt = f"""You are a trend analyst. For EACH cluster of trending social media posts below (grouped by semantic similarity), identify the common theme.

{chr(10).join(sections)}

Return ONLY valid JSON: an object mapping each cluster's number (as a string key) to {{"theme": "3-6 words", "summary": "1-2 sentences"}}. Include an entry for every cluster listed above. Example shape:
{{"0": {{"theme": "AI in everyday life", "summary": "..."}}, "1": {{"theme": "...", "summary": "..."}}}}"""

    # Bounded by cluster count so a bigger batch doesn't get silently
    # truncated mid-JSON — ~120 tokens/cluster covers theme+summary+overhead.
    response = _anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=min(120 * len(clusters) + 200, 8192),
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip() if response.content else ""
    if not raw:
        # Seen in practice (previously per-cluster, same failure mode can
        # still happen for the whole batch): Haiku occasionally returns
        # empty content with no explicit refusal message — json.loads("")
        # raises the unhelpful "Expecting value: line 1 column 1 (char 0)".
        # Raise something diagnosable instead.
        raise ValueError("Claude returned empty content for batch cluster labeling")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip("```json").strip("```").strip()
        parsed = json.loads(cleaned)

    result = {}
    for label, _trends in clusters:
        entry = parsed.get(str(label))
        if isinstance(entry, dict) and entry.get("theme"):
            result[label] = entry
    return result


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
        # (label, cluster_trends, fingerprint, momentum, previous_size) for
        # clusters that don't have an exact-membership match and need a
        # fresh AI label — collected here, labeled in one batched call
        # below, rather than one API call per cluster inline in this loop.
        to_label = []
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

            to_label.append((label, cluster_trends, fp, momentum, previous_size))

        # One batched Anthropic call for every cluster needing a label,
        # instead of one call per cluster — see _ai_label_clusters_batch.
        # Isolated at the batch level: one bad/empty response fails every
        # cluster in this run's to_label set, same as before (one bad call
        # used to fail one cluster; now it's one call for all of them), not
        # a regression in isolation, just a different unit of failure.
        try:
            labels_by_id = _ai_label_clusters_batch([(label, t) for label, t, _, _, _ in to_label])
        except Exception as e:
            logger.warning("Batch AI labeling failed for %d clusters: %s", len(to_label), e)
            labels_by_id = {}

        created = 0
        failed = 0
        for label, cluster_trends, fp, momentum, previous_size in to_label:
            ai_label = labels_by_id.get(label)
            if not ai_label:
                logger.warning("AI labeling failed for a cluster (label=%s, size=%d) — skipping",
                                label, len(cluster_trends))
                failed += 1
                continue

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

        # Data-loss safety net, confirmed live: a total provider outage
        # (Anthropic credits exhausted) meant EVERY candidate cluster failed
        # labeling in one run, surviving_ids ended up empty, and the "delete
        # anything not reused/created this run" step below wiped every
        # existing cluster — the entire live Cluster table gone in one bad
        # run, with no grace period. If this run had clusters that needed
        # labeling but got zero successes out of them (and nothing was
        # reused either), that's a systemic failure, not genuine trend
        # turnover — preserve what already existed instead of deleting it.
        # A normal run, even a partially-failing one, still has created>0
        # or reused>0 and prunes stale clusters exactly as before.
        if to_label and created == 0 and reused == 0:
            logger.error(
                "Clustering run produced zero successful clusters out of %d candidates "
                "(all labeling failed) — preserving %d existing cluster(s) instead of "
                "wiping them.", len(to_label), len(all_existing_clusters),
            )
            session.commit()
            return {
                "clusters": len(all_existing_clusters),
                "clusters_created": 0,
                "clusters_reused": 0,
                "clusters_removed": 0,
                "clusters_failed": failed,
                "noise": noise_count,
                "total_trends": len(trends),
                "warning": "All cluster labeling failed this run — existing clusters preserved, not refreshed.",
            }

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
            "clusters_failed": failed,
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
