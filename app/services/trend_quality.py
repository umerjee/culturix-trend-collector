"""Trend/cluster quality scoring — the shared signal both clustering paths use to
answer "is this a real, lasting theme or noise" from data we actually have.

There is no user-engagement ground truth yet (0 rows in ContentPostSnapshot, 3 real
users) to learn a preference model from, so this is deliberately NOT framed as ML:
v1 is a transparent, weighted formula over real signals, calibrated against measured
data distributions the same way PERSONA_MATCH_MIN_SCORE was in region_daily_summary.py
— not fitted against outcomes, because there aren't any yet. A documented v2 (not
built here) would recalibrate these weights against internal-consistency checks (does
a high score predict slower content_check_log relevance decay; does it agree with
trend_validator.py's independently-produced durability tag) once enough history exists
— still not engagement-based, since that data doesn't exist.

Two independent clustering paths, two entry points here:

- score_group() — for app.models.cluster.Cluster (HDBSCAN path, app/clustering_service.py).
  Scores both persisted Cluster rows and raw ungrouped "source" buckets
  (app/routers/world.py's list_world_trend_digest) on one scale, from the same
  aggregate shape both already reduce to: how many signals, across how many distinct
  platforms, how textually repetitive. Confirmed live motivating case: a single
  repeated TikTok hashtag caption (163 near-duplicate posts, one platform) previously
  outranked a real 4-signal curated Cluster theme under a pure signal_count sort.

- score_history() — for clusterer.py's separate in-memory path (Voyage+Qdrant+DeepSeek),
  which never touches the Cluster table at all. That path's persistence signal already
  exists and is correctly computed (trend_historian.py's recurrence_pattern/
  pattern_confidence, trend_validator.py's durability) — this just turns it into a
  comparable score for persona_mapper.py's cluster ranking, which currently ignores it.

A note on cohesion vs. diversity, since they sound similar but measure opposite
things: Cluster.cohesion (embedding-based average pairwise similarity) tells you how
tightly related a cluster's members are — but the motivating spam case (163 near-
identical captions) is HIGHLY cohesive by that measure, not low. Embedding cohesion
doesn't discriminate "one coherent real theme" from "one repeated post," so it is
computed and stored as informational metadata (giving the long-dead Cluster.cohesion
column a real value for the first time) but is NOT part of the quality score. The
signal that actually catches near-duplicate spam is textual: how many distinct
normalized titles appear versus how many signals total.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from math import log

# Weights are explicit constants, not hidden in the formula, and are marked as a
# starting point rather than a tuned result: they have not yet been calibrated
# against a real post-Phase-0 momentum distribution (momentum was 100% NULL before
# that fix), let alone backtested against any outcome. Revisit once real data exists.
_WEIGHT_PERSISTENCE = 0.35
_WEIGHT_CORROBORATION = 0.30
_WEIGHT_DIVERSITY = 0.25
_WEIGHT_SIZE = 0.10

# Bump whenever the weights/formula change, so a future backtest can join a score
# against a later outcome and know which formula version produced it.
WEIGHTS_VERSION = 1

# Diminishing returns on platform count: going from 1 to 2 platforms matters far more
# than 3 to 4. Values beyond the last key are treated as the last value.
_CORROBORATION_BY_PLATFORM_COUNT = {1: 0.0, 2: 0.55, 3: 0.8}
_CORROBORATION_MAX = 1.0

# log-dampened so a single huge repeated-post bucket can't dominate purely on count,
# matching the exact failure mode this was built to fix.
_SIZE_SATURATION = 20


@dataclass
class QualityScore:
    score: float
    persistence: float
    corroboration: float
    diversity: float
    size_factor: float
    weights_version: int = WEIGHTS_VERSION
    computed_at: datetime = field(default_factory=datetime.utcnow)

    def as_components(self) -> dict:
        """JSON-serializable breakdown for Cluster.quality_components."""
        return {
            "persistence": round(self.persistence, 4),
            "corroboration": round(self.corroboration, 4),
            "diversity": round(self.diversity, 4),
            "size_factor": round(self.size_factor, 4),
            "weights_version": self.weights_version,
        }


def _corroboration(platform_count: int) -> float:
    if platform_count <= 0:
        return 0.0
    if platform_count in _CORROBORATION_BY_PLATFORM_COUNT:
        return _CORROBORATION_BY_PLATFORM_COUNT[platform_count]
    return _CORROBORATION_MAX


def _size_factor(signal_count: int) -> float:
    if signal_count <= 0:
        return 0.0
    return min(1.0, log(signal_count + 1) / log(_SIZE_SATURATION))


def _persistence_from_momentum(momentum: str | None) -> float:
    """Cluster.momentum is only meaningful once a cluster has been seen more than
    once (see clustering_service.py's _compute_momentum) — None means either a
    first sighting or a raw source bucket with no Cluster at all. Neither is
    penalized (unknown != low-quality), just not credited; 'up' gets full credit
    as the clearest real-persistence signal, 'neutral' partial (it recurred, just
    isn't currently growing), 'down' none (fading)."""
    return {"up": 1.0, "neutral": 0.6, "down": 0.0}.get(momentum or "", 0.0)


def score_group(*, signal_count: int, platforms: set, title_keys: set,
                momentum: str | None = None) -> QualityScore:
    """Pure function: no session, no query, no embeddings — the aggregate shape
    app/routers/world.py's list_world_trend_digest already accumulates per group
    while it loops over trends once. Works identically for a persisted Cluster
    group (pass its Cluster.momentum) and a raw ungrouped source bucket (pass
    momentum=None)."""
    persistence = _persistence_from_momentum(momentum)
    corroboration = _corroboration(len(platforms))
    diversity = (len(title_keys) / signal_count) if signal_count > 0 else 0.0
    size_factor = _size_factor(signal_count)

    score = (
        _WEIGHT_PERSISTENCE * persistence
        + _WEIGHT_CORROBORATION * corroboration
        + _WEIGHT_DIVERSITY * diversity
        + _WEIGHT_SIZE * size_factor
    )
    return QualityScore(score=round(score, 4), persistence=persistence, corroboration=corroboration,
                        diversity=diversity, size_factor=size_factor)


def compute_cohesion(embeddings: list) -> float | None:
    """Average pairwise cosine similarity of a cluster's own trend embeddings —
    informational only (see module docstring for why this is not part of the
    quality score). None for fewer than 2 embeddings (undefined for a singleton)."""
    if len(embeddings) < 2:
        return None
    total, pairs = 0.0, 0
    for i in range(len(embeddings)):
        for j in range(i + 1, len(embeddings)):
            a, b = embeddings[i], embeddings[j]
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(y * y for y in b) ** 0.5
            if norm_a and norm_b:
                total += dot / (norm_a * norm_b)
                pairs += 1
    return round(total / pairs, 4) if pairs else None


def score_and_persist_cluster(cluster, cluster_trends: list, embeddings: list) -> QualityScore:
    """Called from clustering_service.run_clustering's per-cluster loop (both the
    reuse and creation branches) — embeddings for this cluster's trends are already
    in memory there, so cohesion is free to compute correctly for the first time.
    Mutates and returns; does not commit (the caller's existing session.commit()
    at the end of run_clustering covers this too)."""
    title_keys = {_trend_title_key(t) for t in cluster_trends}
    result = score_group(
        signal_count=len(cluster_trends),
        platforms={t.platform for t in cluster_trends if t.platform},
        title_keys=title_keys,
        momentum=cluster.momentum,
    )
    cluster.cohesion = compute_cohesion(embeddings)
    cluster.quality_score = result.score
    cluster.quality_components = result.as_components()
    cluster.quality_computed_at = datetime.utcnow()
    return result


def _trend_title_key(trend) -> str:
    text = (getattr(trend, "title", None) or getattr(trend, "content", None) or "").lower()
    return re.sub(r"\W+", " ", text).strip()[:60]


# ── Path B: the separate in-memory clusterer.py / trend_historian.py path ─────

# recurrence_pattern values, from most to least "proven persistent" — mirrors
# trend_historian.py's own durability grounding (weekly/yearly/sustained treated
# as real recurrence, spike as a one-off, unclear/None as no pattern yet).
_HISTORY_PATTERN_SCORE = {"weekly": 1.0, "yearly": 1.0, "sustained": 0.85, "spike": 0.15}
_DURABILITY_SCORE = {"sustained": 1.0, "spike": 0.15}


def score_history(cluster: dict) -> float:
    """0.0-1.0 persistence score for one of clusterer.py's in-memory cluster dicts,
    from trend_historian.py's cluster['history'] (recurrence_pattern/pattern_confidence)
    and trend_validator.py's cluster['durability'] — both already computed correctly,
    just never turned into a number persona_mapper.py's ranking could use. Prefers the
    pattern-confidence-weighted recurrence signal (grounded in real occurrence counts)
    and falls back to the LLM-judged durability tag alone when there's no history yet
    (a cluster's first day, before trend_historian.py has ≥3 occurrences to pattern-match)."""
    history = cluster.get("history") or {}
    pattern = history.get("recurrence_pattern")
    if pattern and pattern in _HISTORY_PATTERN_SCORE:
        confidence = history.get("pattern_confidence")
        confidence = confidence if isinstance(confidence, (int, float)) else 0.5
        return round(_HISTORY_PATTERN_SCORE[pattern] * max(0.5, confidence), 4)

    durability = cluster.get("durability")
    return _DURABILITY_SCORE.get(durability, 0.0)
