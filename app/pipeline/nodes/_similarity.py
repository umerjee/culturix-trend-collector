"""Shared embedding-similarity helpers for cross-day recurrence tracking —
used by trend_historian.py (TrendTheme) and persona_tag_tracker.py (Persona),
both of which match a fresh embedding against a running centroid to decide
"is this the same recurring thing we've seen before." Extracted here so the
two nodes don't carry their own private, silently-divergent copies of this
math."""

# Both consumers embed "{name}. {description}" via Voyage's voyage-3 model
# (no input_type specified — symmetric/general-purpose mode) on short,
# freshly LLM-generated text, and both were originally set to 0.85 as a
# guess with no measurement behind it.
#
# Recalibrated 2026-07-23 after a real-data audit found /admin/trend-history
# stuck at 103/103 themes showing "unclear" — every theme capped at
# occurrence_count 1-2 despite 4 days of real operation. Pulled actual
# same-real-world-topic pairs from production (same day's LLM re-wording a
# recurring trend) and measured their true cosine similarity directly:
#   "Lamine Yamal rising stardom" <-> "...Football Star Hype"      0.844
#   "FIFA World Cup 2026 hype" <-> "2026 FIFA World Cup"           0.808
#   "AI Influencer Monetization" <-> itself, reworded description  0.798
#   "The Odyssey 2026 film buzz" <-> "...Film Phenomenon"          0.793
#   "Kaylee Hottle rising star" <-> "...Career Breakthrough"       0.769
# Every one of these — genuinely the same real-world trend, one day apart —
# fell below the old 0.85 threshold, meaning matching was silently failing
# on almost every real recurrence. 0.75 was chosen to catch all five of the
# above while still excluding the more tangentially-related pairs also
# measured that day (e.g. general "World Cup sports culture" discourse vs.
# the specific FIFA hype cluster, at 0.54-0.55) — a deliberate, evidence-
# based judgment call, not a definitive number; revisit if false-positive
# merges (unrelated trends folding into the same theme) turn out to be a
# problem at this level, or if occurrence counts still aren't climbing after
# a couple more weeks of real data.
#
# Recalibrated again 2026-09-16: exactly that revisit trigger fired —
# occurrence counts still weren't climbing (96% of 647 themes across ~7
# weeks stuck at 1 occurrence). Brute-forced cosine similarity across every
# pair of single-occurrence (undrifted) theme embeddings in production and
# found the SAME failure mode as the 0.85->0.75 change, just less severe:
# clear same-story pairs, ONE DAY apart, scoring just under 0.75 --
# "Avengers: Doomsday Doctor Doom MCU" <-> "Avengers Doomsday Doctor Doom"
# (0.747), "Unruly Aircraft Passenger Duct-Tape Incident" <-> "Unruly
# passenger duct taped" (0.730), "Silo Season 3 Finale Drama" <-> "Silo
# Season 3 Episode 9 Finale" (0.709), "Lily Hooper Australian Missing
# Hiker" <-> "Lily Hooper missing hiker found dead Australia" (0.704).
# 0.70 catches all of these while the surrounding score band (0.63-0.70:
# "Reacher Season 4 Release" vs "...Episode 6 Cliffhanger" 0.690, "Trump
# Declares Economic War on Iran" vs "...Iran Economic D-Day sanctions"
# 0.681, "King Harald V of Norway Death" vs "...Death Mourning" 0.648) is
# ALSO mostly genuine same-story pairs, not false-positive territory --
# but going much lower than 0.70 starts running into pairs like "Basketball
# Culture and Debates" vs "WNBA Sports Trending Interest" (0.570) that are
# related-but-distinct, not the same story. No single fixed threshold
# cleanly separates same-story from different-story in this embedding
# space (the two distributions genuinely overlap) — 0.70 is a real,
# evidence-based improvement over 0.75, not a guaranteed-clean cutoff;
# expect some remaining false negatives in the 0.60s, same as before.
SIMILARITY_THRESHOLD = 0.70


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
