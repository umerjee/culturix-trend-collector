"""Shared embedding-similarity helpers for cross-day recurrence tracking —
used by trend_historian.py (TrendTheme) and persona_tag_tracker.py (Persona),
both of which match a fresh embedding against a running centroid to decide
"is this the same recurring thing we've seen before." Extracted here so the
two nodes don't carry their own private, silently-divergent copies of this
math."""


def cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def average_embedding(centroid: list, new_vec: list, n: int) -> list:
    """Running average weighted by n prior occurrences, so early occurrences
    aren't drowned out but the centroid still drifts to track wording drift."""
    if not centroid or n <= 0:
        return new_vec
    return [(c * n + v) / (n + 1) for c, v in zip(centroid, new_vec)]
