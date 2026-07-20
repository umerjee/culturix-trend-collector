"""
Trend Historian — persists each run's approved clusters into a durable, cross-day
trend history (TrendTheme + TrendOccurrence) and attaches recurrence context back
onto the cluster dict so downstream nodes can consult real history instead of
guessing fresh every run:
  - content_strategist.py phrases ideas with pattern-awareness (e.g. a usual
    Friday spike) instead of treating every trend as a first-time blip.
  - trend_validator.py's durability tag gets grounded in observed occurrences
    once there are enough of them, instead of staying a single day's LLM guess.

Cluster naming/wording is a fresh LLM call every run (clusterer.py), so "is this
the same trend we saw last week" can't be exact-string matching — clusters are
matched to a TrendTheme by embedding similarity against a running centroid.

Fail-open: if embedding or persistence fails, skip history for this run and log
a warning — a history outage must never take down the daily pipeline.
"""
import logging
from collections import Counter
from datetime import date, datetime

from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.trend_historian")

_SIMILARITY_THRESHOLD = 0.85
_MIN_OCCURRENCES_FOR_PATTERN = 3


def _cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _average_embedding(centroid: list, new_vec: list, n: int) -> list:
    """Running average weighted by n prior occurrences, so early occurrences
    aren't drowned out but the centroid still drifts to track wording drift."""
    if not centroid or n <= 0:
        return new_vec
    return [(c * n + v) / (n + 1) for c, v in zip(centroid, new_vec)]


def _compute_recurrence(occurrence_dates: list) -> tuple:
    """Pure heuristic over a theme's occurrence dates — no ML.
    Returns (recurrence_pattern, dominant_day_of_week, confidence)."""
    dates = sorted(occurrence_dates)
    if len(dates) < _MIN_OCCURRENCES_FOR_PATTERN:
        return "unclear", None, 0.0

    span_days = (dates[-1] - dates[0]).days
    weekday_counts = Counter(d.weekday() for d in dates)
    dominant_day, dominant_hits = weekday_counts.most_common(1)[0]
    dominant_ratio = dominant_hits / len(dates)

    if span_days >= 14 and dominant_ratio >= 0.6:
        return "weekly", dominant_day, round(dominant_ratio, 2)

    # Yearly: occurrences form a tight cluster (<=45 days) within a given year,
    # and those per-year clusters land in roughly the same calendar window
    # (within 30 days) across at least two distinct years.
    if span_days >= 300:
        by_year: dict = {}
        for d in dates:
            by_year.setdefault(d.year, []).append(d)
        year_midpoints = []
        for year_dates in by_year.values():
            year_dates = sorted(year_dates)
            if (year_dates[-1] - year_dates[0]).days <= 45:
                midpoint = year_dates[len(year_dates) // 2]
                year_midpoints.append(midpoint.timetuple().tm_yday)
        year_midpoints.sort()
        close_pairs = sum(
            1 for i in range(1, len(year_midpoints))
            if year_midpoints[i] - year_midpoints[i - 1] <= 30
        )
        if close_pairs >= 1:
            confidence = round(close_pairs / (len(year_midpoints) - 1), 2)
            return "yearly", None, confidence

    # Sustained: shows up frequently and steadily over a long span with no
    # single dominant weekday — an ongoing interest rather than a one-off.
    weeks_spanned = max(span_days / 7, 1)
    if span_days >= 21 and (len(dates) / weeks_spanned) >= 0.7:
        return "sustained", None, round(min(len(dates) / weeks_spanned, 1.0), 2)

    return "spike", None, 0.5


def _cluster_text(cluster: dict) -> str:
    return f"{cluster.get('name', '')}. {cluster.get('description', '')}".strip()


def map_trend_history(state: PipelineState) -> PipelineState:
    clusters = state.get("clusters", [])
    if not clusters:
        return state

    from app.embeddings import embed_batch

    try:
        vectors = embed_batch([_cluster_text(c) for c in clusters])
    except Exception as e:
        logger.warning("Embedding clusters for history failed — skipping trend history this run: %s", e)
        state["errors"] = state.get("errors", []) + [f"trend_historian: {e}"]
        return state

    from app.db import SessionLocal
    from app.models.trend_theme import TrendTheme
    from app.models.trend_occurrence import TrendOccurrence

    today = datetime.utcnow().date()
    session = SessionLocal()
    try:
        themes = session.query(TrendTheme).all()

        for cluster, vector in zip(clusters, vectors):
            if not vector:
                continue
            try:
                theme = _match_or_create_theme(session, themes, cluster, vector, today)

                occurrence_dates = [
                    row.occurrence_date for row in
                    session.query(TrendOccurrence.occurrence_date)
                    .filter(TrendOccurrence.theme_id == theme.id)
                    .all()
                ]
                if today not in occurrence_dates:
                    occurrence_dates.append(today)

                pattern, dominant_day, confidence = _compute_recurrence(occurrence_dates)
                theme.recurrence_pattern = pattern
                theme.dominant_day_of_week = dominant_day
                theme.pattern_confidence = confidence

                # Ground durability in observed history once there's enough of it —
                # a single day's LLM guess shouldn't outrank a real pattern.
                if theme.occurrence_count >= _MIN_OCCURRENCES_FOR_PATTERN:
                    if pattern in ("weekly", "yearly", "sustained"):
                        cluster["durability"] = "sustained"
                    elif pattern == "spike":
                        cluster["durability"] = "spike"

                cluster["history"] = {
                    "theme_id": theme.id,
                    "first_seen_at": theme.first_seen_at.isoformat() if theme.first_seen_at else None,
                    "occurrence_count": theme.occurrence_count,
                    "recurrence_pattern": pattern,
                    "dominant_day_of_week": dominant_day,
                }
            except Exception as e:
                logger.warning("Trend history mapping failed for cluster %r: %s", cluster.get("name"), e)
                state["errors"] = state.get("errors", []) + [f"trend_historian:{cluster.get('name')}:{e}"]
                continue

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Trend history persistence failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"trend_historian: {e}"]
    finally:
        session.close()

    return state


def _match_or_create_theme(session, themes: list, cluster: dict, vector: list, today: date):
    from app.models.trend_theme import TrendTheme
    from app.models.trend_occurrence import TrendOccurrence

    best_theme, best_score = None, 0.0
    for theme in themes:
        score = _cosine_similarity(theme.centroid_embedding or [], vector)
        if score > best_score:
            best_theme, best_score = theme, score

    if best_theme and best_score >= _SIMILARITY_THRESHOLD:
        theme = best_theme
        already_seen_today = (
            session.query(TrendOccurrence)
            .filter(TrendOccurrence.theme_id == theme.id, TrendOccurrence.occurrence_date == today)
            .first()
        )
        if already_seen_today is None:
            session.add(TrendOccurrence(
                theme_id=theme.id,
                occurrence_date=today,
                day_of_week=today.weekday(),
                name_snapshot=cluster.get("name", ""),
                description_snapshot=cluster.get("description", ""),
                size=len(cluster.get("example_posts") or []),
                durability=cluster.get("durability"),
            ))
            theme.centroid_embedding = _average_embedding(
                theme.centroid_embedding, vector, theme.occurrence_count or 0
            )
            theme.occurrence_count = (theme.occurrence_count or 0) + 1
        theme.last_seen_at = datetime.utcnow()
        theme.canonical_name = cluster.get("name") or theme.canonical_name
        theme.description = cluster.get("description") or theme.description
        theme.emotional_theme = cluster.get("emotional_theme") or theme.emotional_theme
        return theme

    theme = TrendTheme(
        canonical_name=cluster.get("name", ""),
        description=cluster.get("description", ""),
        emotional_theme=cluster.get("emotional_theme"),
        centroid_embedding=vector,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        occurrence_count=1,
        recurrence_pattern="unclear",
    )
    session.add(theme)
    session.flush()  # assign theme.id for the occurrence FK below
    themes.append(theme)
    session.add(TrendOccurrence(
        theme_id=theme.id,
        occurrence_date=today,
        day_of_week=today.weekday(),
        name_snapshot=cluster.get("name", ""),
        description_snapshot=cluster.get("description", ""),
        size=len(cluster.get("example_posts") or []),
        durability=cluster.get("durability"),
    ))
    return theme
