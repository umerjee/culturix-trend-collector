"""Culturix Ingestion & Validation Engine — extracts structured items from
raw text (real Wikipedia extracts, real UNESCO World Heritage data, or a
batch of already-collected Trend rows), classifies each into one of 8
categories, scores it on 4 weighted metrics, runs an LLM "challenge"
critique, decides include/exclude/store_for_later, and assigns a fixed
per-category lifecycle profile. See app/models/curated_item.py for the
persisted shape and scripts/ingest_and_score.py for the CLI entry point.

Supersedes app/services/culturetoon_script.py::suggest_world_subjects_from_trends
(retired) — that function only ever proposed World Feature subject ideas
from Trend rows with no scoring/challenge/persistence at all.

Two real LLM calls per item (not one per pipeline step) — extraction is one
call per source text (can yield several items), scoring+challenge is one
call per item (holistic judgment, same reasoning app/pipeline/nodes/
content_check.py already uses for scoring trend+freshness together rather
than separately). priority_score itself is deterministic Python, not
LLM-decided — the weighting formula is fixed, not a judgment call.
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta

logger = logging.getLogger("culturix.services.culturix_ingestion")

CATEGORIES = ["history", "archaeology", "culture", "humor", "tech", "innovation", "trending", "geopolitical"]

# Transcribed directly from the Culturix Ingestion & Validation Engine spec
# — a fixed lookup by category, not an LLM judgment call. auto_archive=True
# means this category's items are expected to go stale fast (humor,
# trending) and should be swept without a human decision; the rest need a
# human call before archiving even past their lifespan.
DURATION_PROFILES: dict[str, dict] = {
    "history":      {"lifespan_days": 99999, "refresh_frequency_days": 3650, "decay_rate": 0.0, "auto_archive": False},
    "archaeology":  {"lifespan_days": 3650,  "refresh_frequency_days": 365,  "decay_rate": 0.1, "auto_archive": False},
    "culture":      {"lifespan_days": 900,   "refresh_frequency_days": 180,  "decay_rate": 0.2, "auto_archive": False},
    "humor":        {"lifespan_days": 30,    "refresh_frequency_days": 7,    "decay_rate": 0.9, "auto_archive": True},
    "tech":         {"lifespan_days": 540,   "refresh_frequency_days": 90,   "decay_rate": 0.3, "auto_archive": False},
    "innovation":   {"lifespan_days": 540,   "refresh_frequency_days": 90,   "decay_rate": 0.3, "auto_archive": False},
    "trending":     {"lifespan_days": 3,     "refresh_frequency_days": 1,    "decay_rate": 1.0, "auto_archive": True},
    "geopolitical": {"lifespan_days": 720,   "refresh_frequency_days": 120,  "decay_rate": 0.2, "auto_archive": False},
}

# Neutral fallback on any LLM failure — same fail-open posture
# content_check.py already uses ({"score": 50} on its own scoring calls) —
# a scoring outage should never crash an ingestion batch over one bad item.
_NEUTRAL_SCORES = {"recency_score": 50, "popularity_score": 50, "cultural_weight": 50, "evergreen_value": 50}


class IngestionError(Exception):
    pass


def _get_qwen_client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")


def _get_claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _call_llm_json(prompt: str, temperature: float = 0.4, max_tokens: int = 1200) -> dict:
    """Same shared Qwen-max (primary) / Claude Haiku (fallback) JSON-mode
    call as culturetoon_script.py's own _call_llm_json — duplicated rather
    than imported, matching this codebase's established convention of small
    duplicated helpers over cross-module coupling (see e.g. EXPRESSION_NAMES
    in that same module). One retry on a transient transport failure (a live
    run hit a one-off "Connection error"); malformed JSON is not retried.
    Raises IngestionError on any failure."""
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            if os.getenv("QWEN_API_KEY"):
                response = _get_qwen_client().chat.completions.create(
                    model="qwen-max", messages=[{"role": "user", "content": prompt}], temperature=temperature,
                )
                raw = response.choices[0].message.content
            else:
                message = _get_claude_client().messages.create(
                    model="claude-haiku-4-5-20251001", max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = message.content[0].text
            return _parse(raw)
        except json.JSONDecodeError as exc:
            raise IngestionError(f"Model returned invalid JSON: {exc}") from exc
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning("LLM call failed (%s); retrying once", exc)
                time.sleep(1.5)
    raise IngestionError(str(last_exc)) from last_exc


def extract_items(source_type: str, region: str | None, raw_text: str, max_items: int = 5) -> list[dict]:
    """Extracts up to `max_items` structured items from real raw text — one
    LLM call. Returns [{"title", "summary", "category"}, ...], or [] if the
    text doesn't genuinely contain that many distinct items (never pads
    with invented ones) or the call fails.

    Do NOT invent historical facts — instructed explicitly in the prompt,
    same "grounded, not fabricated" posture as every other content-
    generation function in this codebase (see e.g. generate_world_script's
    own trend-grounding)."""
    region_line = f"Region: {region}\n" if region else ""
    prompt = f"""Extract up to {max_items} meaningful, DISTINCT items from the raw text below. An item may be a
historical event, an archaeological discovery, a cultural practice or fact, a meme or humor
element, a technological breakthrough, an innovation highlight, a trending topic, or a
geopolitical development.

Do NOT invent facts not present in the text. Clean noisy text (strip boilerplate, citations,
navigation artifacts) but do not add anything the source doesn't actually say. If the text
genuinely only supports fewer than {max_items} distinct items, return fewer — never pad.

Source type: {source_type}
{region_line}Raw text:
{raw_text[:6000]}

Return ONLY valid JSON: {{"items": [{{"title": string, "summary": string (1-3 clean sentences),
"category": one of {CATEGORIES}}}]}}"""

    try:
        parsed = _call_llm_json(prompt, temperature=0.3, max_tokens=1200)
    except IngestionError as exc:
        logger.warning("Item extraction failed for source_type=%s: %s", source_type, exc)
        return []
    items = parsed.get("items") or []
    return [i for i in items if i.get("title") and i.get("summary") and i.get("category") in CATEGORIES][:max_items]


def score_and_challenge(item: dict) -> dict:
    """One LLM call per item: scores it on the 4 weighted metrics AND runs
    the challenge critique in the same call (holistic judgment — the
    challenge reasoning and the scores inform each other, same reasoning
    content_check.py scores trend/freshness together rather than as
    separate calls). Returns {recency_score, popularity_score,
    cultural_weight, evergreen_value, challenge_notes, pipeline_decision}.
    Fails open to _NEUTRAL_SCORES + "store_for_later" on any LLM error —
    never crashes a batch over one bad item, matching content_check.py's
    own {"score": 50} fallback posture."""
    prompt = f"""Score this item for Culturix, a platform that turns culturally meaningful content into
short videos organized by world region.

Title: {item['title']}
Category: {item['category']}
Summary: {item['summary']}

Score each 0-100:
- recency_score: how recent or time-relevant this is
- popularity_score: how widely discussed, searched, or referenced
- cultural_weight: importance to identity, heritage, or society
- evergreen_value: long-term significance independent of trends

Then challenge it honestly — most items should NOT pass:
- Is it redundant with extremely common knowledge?
- Is it too niche for a general audience, or too broad/vague to be a real subject?
- Is it historically/factually accurate as stated?
- Is it culturally meaningful TODAY, not just historically?
- Does it add real value, or is it filler?

Based on the challenge, decide: "include" (high-value, ready for the content pipeline),
"exclude" (irrelevant, low-value, redundant, or inaccurate), or "store_for_later" (useful but
not a priority right now).

Return ONLY valid JSON: {{"recency_score": int, "popularity_score": int, "cultural_weight": int,
"evergreen_value": int, "challenge_notes": string (1-3 sentences, specific reasoning),
"pipeline_decision": "include" | "exclude" | "store_for_later"}}"""

    try:
        parsed = _call_llm_json(prompt, temperature=0.4, max_tokens=500)
    except IngestionError as exc:
        logger.warning("Scoring failed for item %r: %s", item.get("title"), exc)
        return {**_NEUTRAL_SCORES, "challenge_notes": f"Scoring failed: {exc}", "pipeline_decision": "store_for_later",
                "scoring_failed": True}

    result = dict(_NEUTRAL_SCORES)
    for key in _NEUTRAL_SCORES:
        value = parsed.get(key)
        if isinstance(value, (int, float)):
            result[key] = max(0, min(100, int(value)))
    result["challenge_notes"] = parsed.get("challenge_notes") or ""
    decision = parsed.get("pipeline_decision")
    result["pipeline_decision"] = decision if decision in ("include", "exclude", "store_for_later") else "store_for_later"
    return result


def compute_priority_score(scores: dict) -> int:
    """Pure function — the fixed weighting formula, not an LLM judgment
    call. Matches content_check.py's own precedent of a hardcoded weighted
    formula (trend*0.5 + freshness*0.3 + persona*0.2) over an LLM-decided
    weighting."""
    return round(
        0.30 * scores["recency_score"]
        + 0.30 * scores["popularity_score"]
        + 0.25 * scores["cultural_weight"]
        + 0.15 * scores["evergreen_value"]
    )


def ingest(source_type: str, region: str | None, raw_text: str, session, max_items: int = 5,
           source_ref: str | None = None, source_url: str | None = None) -> list:
    """Runs the full extract -> score+challenge -> priority -> lifecycle
    pipeline over one raw text and persists the results as CuratedItem
    rows, deduped by (source_type, source_ref). When an upstream source
    reference is supplied, the stored key combines it with the extracted
    title so one source document can yield several distinct items without
    suppressing later items on re-ingestion.
    Returns the list of newly-created CuratedItem rows (skips duplicates,
    does not update existing ones — re-ingesting is a deliberate refresh
    action, not implicit)."""
    from app.models.curated_item import CuratedItem

    items = extract_items(source_type, region, raw_text, max_items=max_items)
    if not items:
        return []

    def _stable_ref(item: dict) -> str:
        # source_ref is VARCHAR(200) — an over-long title must not fail the insert.
        return (f"{source_ref}:{item['title']}" if source_ref else item["title"])[:200]

    refs = [_stable_ref(i) for i in items]
    existing = {
        r[0] for r in session.query(CuratedItem.source_ref)
        .filter(CuratedItem.source_type == source_type, CuratedItem.source_ref.in_(refs)).all()
    }
    # End the read transaction now: the scoring calls below are slow, and a
    # connection held idle inside an open transaction is dropped by Supabase's
    # pooler (a live run failed on commit with "server closed the connection
    # unexpectedly"). The insert phase then checks out a fresh connection.
    session.rollback()

    rows = []
    for item, stable_ref in zip(items, refs):
        if stable_ref in existing:
            continue
        scores = score_and_challenge(item)
        if scores.get("scoring_failed"):
            # An unscored item is not curated — persisting neutral 50s would
            # pollute the ranking, and skipping it lets a re-run retry it.
            logger.warning("Skipping %r: scoring failed, not persisted", item["title"])
            continue
        priority = compute_priority_score(scores)
        profile = DURATION_PROFILES[item["category"]]
        now = datetime.utcnow()
        rows.append(CuratedItem(
            source_type=source_type, source_ref=stable_ref, region=region, source_url=source_url,
            title=item["title"], summary=item["summary"], raw_text=raw_text[:6000],
            category=item["category"],
            recency_score=scores["recency_score"], popularity_score=scores["popularity_score"],
            cultural_weight=scores["cultural_weight"], evergreen_value=scores["evergreen_value"],
            priority_score=priority, challenge_notes=scores["challenge_notes"],
            pipeline_decision=scores["pipeline_decision"],
            lifespan_days=profile["lifespan_days"], refresh_frequency_days=profile["refresh_frequency_days"],
            decay_rate=profile["decay_rate"], auto_archive=profile["auto_archive"],
            expires_at=now + timedelta(days=profile["lifespan_days"]),
        ))
    if rows:
        session.add_all(rows)
        session.commit()
        for row in rows:
            session.refresh(row)
    return rows
