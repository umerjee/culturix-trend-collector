"""Trend-to-culture editorial workflow for CultureToons (internal/admin only).

A candidate pairs a current trend in a country with a curated historical/cultural source from
the same country (the "local connection"). An operator reviews candidates, generates a comedy
script whose facts may come ONLY from the source, and records where it was posted and how it did.

Three rules shape this module:
- Safety exclusions are hard gates, not ranking weights. A screened candidate is blocked and
  never gets a score; an operator cannot clear an automatic hit.
- Trend text never authorizes a factual claim. The writer is told the trend is context only, and
  the fact-checker (judge_world_grounding) is shown the source excerpt alone, so any claim that
  came from the trend is reported as unsupported.
- Ranking is a transparent weighted formula over signals we actually have, not a learned model:
  there is no outcome data yet. Every factor carries a reason the operator can read. Same posture
  as app/services/trend_quality.py.
"""
import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("culturix.services.editorial")

# ── Coverage ──────────────────────────────────────────────────────────────────

# The slate must stay broad: these four are the coverage targets the operator sees gaps for.
TARGET_CONTINENTS = ("Asia", "Americas", "Africa", "Europe")

_CONTINENT_BY_REGION = {
    **dict.fromkeys(["GB", "FR", "DE", "IT", "ES", "PT", "PL", "UA", "NL", "BE", "CH", "AT", "SE", "NO", "DK",
                     "FI", "IE", "GR", "CZ", "HU", "RO", "RU"], "Europe"),
    **dict.fromkeys(["US", "CA", "MX", "BR", "AR", "CO", "CL", "PE", "VE", "CU", "EC", "GT", "BO", "UY",
                     "JM"], "Americas"),
    **dict.fromkeys(["NG", "ZA", "EG", "KE", "MA", "GH", "ET", "TZ", "DZ", "TN", "SN", "UG", "CM", "CI",
                     "ZW", "RW"], "Africa"),
    # West Asia (the Middle East) counts as Asia for coverage.
    **dict.fromkeys(["JP", "KR", "IN", "CN", "ID", "PH", "TH", "VN", "MY", "PK", "SG", "BD", "LK", "NP",
                     "TW", "HK", "KH", "MM", "TR", "SA", "AE", "IL", "IR", "IQ", "JO", "LB", "QA", "KZ",
                     "UZ"], "Asia"),
    **dict.fromkeys(["AU", "NZ", "FJ", "PG"], "Oceania"),
}


def continent_for(region: Optional[str]) -> str:
    return _CONTINENT_BY_REGION.get((region or "").upper(), "Other")


# ── Formats ───────────────────────────────────────────────────────────────────

# Test formats from the editorial brief. They are hypotheses to measure, not proven winners.
EDITORIAL_FORMATS = {
    "trend_to_history": "Connect the trend to one surprising detail from the source, then land the joke on the contrast.",
    "then_vs_now": "Contrast how people experience the trend today with how the source's era handled the same need.",
    "surprising_detail": "Open on the single most surprising fact in the source; the cast reacts as the trend's audience would.",
    "character_reaction": "A recurring cast member reacts to the trend, and another answers with a fact from the source.",
}

LANGUAGES = {"en": "English", "fr": "French", "de": "German", "es": "Spanish"}
PLATFORMS = ("tiktok", "instagram", "youtube")

# ── Safety ────────────────────────────────────────────────────────────────────


def _words(*patterns: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b", re.IGNORECASE)


# Applied to the TREND (what is happening now). Any hit blocks the candidate.
_TREND_EXCLUSIONS = {
    "tragedy": _words(r"massacres?", r"genocide", r"death toll", r"killed", r"killings?", r"deaths?", r"died",
                      r"fatal(?:ities|ity)?", r"victims?", r"mourning", r"funerals?", r"traged(?:y|ies)",
                      r"disasters?", r"catastroph(?:e|ic)", r"famine", r"suicides?", r"murder(?:s|ed)?",
                      r"shootings?", r"stabbings?", r"terror(?:ism|ist|ists)?", r"bomb(?:s|ing|ings|ed)?",
                      r"plane crash", r"earthquake", r"tsunami", r"floods?", r"wildfires?", r"hurricane"),
    "active_conflict": _words(r"war", r"warfare", r"invasion", r"invaded?", r"air ?strikes?", r"missiles?",
                              r"shelling", r"ceasefire", r"hostages?", r"front ?line", r"insurgen(?:ts?|cy)",
                              r"militants?", r"troops", r"military offensive", r"drone strikes?"),
    # A current post about faith is excluded outright, not just one about a ritual: measured on real
    # data, a Quran recitation post ("Quran talawat ... #islam") passed a practice-words-only list.
    "religious_worship": _words(r"worship(?:pers|ping)?", r"prayers?", r"praying", r"pilgrimage", r"pilgrims",
                                r"sermons?", r"blasphemy", r"sacrilege", r"qur'?an", r"koran", r"bible", r"gospel",
                                r"torah", r"allah", r"jesus", r"christ", r"islam(?:ic)?", r"muslims?", r"christians?",
                                r"hindus?", r"buddhists?", r"sikhs?", r"jews", r"ramadan", r"eid", r"namaz", r"salah",
                                r"puja", r"bhajans?", r"hymns?", r"recitation", r"tilawat", r"talawat", r"mosques?",
                                r"churche?s?", r"synagogues?", r"gurdwaras?", r"temples?", r"religion", r"religious"),
}

# Applied to the SOURCE. Heritage often involves faith and old wars, so most source mentions are
# review flags; only atrocity and memorial subjects are hard exclusions.
_SOURCE_EXCLUSIONS = {
    "tragedy": _words(r"genocide", r"massacres?", r"holocaust", r"concentration camps?", r"mass graves?",
                      r"slave trade", r"slavery", r"memorial to the victims", r"ethnic cleansing"),
}

_SOURCE_REVIEW = {
    "historic_conflict": _words(r"wars?", r"battles?", r"conquests?", r"siege", r"colonial(?:ism)?",
                                r"invasions?", r"rebellions?", r"revolution"),
    "religion": _words(r"temples?", r"church(?:es)?", r"mosques?", r"cathedrals?", r"shrines?", r"sacred",
                       r"religious", r"worship", r"pilgrimage", r"monaster(?:y|ies)", r"synagogues?"),
}

# Every key must be affirmed (true) before a candidate can be cleared.
SAFETY_CHECKLIST = {
    "no_tragedy_conflict_worship": "The joke is not about a tragedy, an active conflict or religious worship.",
    "no_real_person_target": "No real, named person is the target of a joke.",
    "culture_not_punchline": "No culture, nationality or ethnicity is the punchline.",
    "framing_checked": "The cultural framing has been checked (by someone familiar with the culture where it is sensitive).",
}


def _hits(patterns: dict, text: str) -> list:
    found = []
    for category, pattern in patterns.items():
        terms = sorted({m.group(0).lower() for m in pattern.finditer(text or "")})
        if terms:
            found.append({"category": category, "terms": terms})
    return found


def screen_safety(trend_text: str, source_text: str) -> dict:
    """{"exclusions": [...], "review": [...]}. Any exclusion is a hard block. Review flags tell the
    operator what to look at before signing the checklist; they never block on their own."""
    exclusions = [{**h, "where": "trend"} for h in _hits(_TREND_EXCLUSIONS, trend_text)]
    exclusions += [{**h, "where": "source"} for h in _hits(_SOURCE_EXCLUSIONS, source_text)]
    review = [{**h, "where": "source"} for h in _hits(_SOURCE_REVIEW, source_text)]
    return {"exclusions": exclusions, "review": review}


# ── Ranking ───────────────────────────────────────────────────────────────────

# Starting weights, not tuned against outcomes (there are none yet). Bump the version on any
# change so a later analysis can tell which formula ranked a candidate.
RANK_WEIGHTS = {"trend_momentum": 0.25, "source_quality": 0.25, "cultural_relevance": 0.25,
                "novelty": 0.15, "cast_fit": 0.10}
RANK_WEIGHTS_VERSION = 2  # v2: single posts scored as weaker evidence; relevance on title+summary

_MOMENTUM_SCORE = {"up": (1.0, "Growing since it was last seen"),
                   "neutral": (0.6, "Recurring, not currently growing"),
                   "down": (0.1, "Fading since it was last seen")}


def _trend_momentum(momentum: Optional[str], quality: Optional[float], kind: str = "cluster") -> tuple:
    if kind == "trend":
        return 0.2, "A single post, not a confirmed trend (no cluster of related posts)"
    base, reason = _MOMENTUM_SCORE.get(momentum or "", (0.4, "First sighting: no history to judge momentum yet"))
    if quality is None:
        return base, reason
    score = 0.6 * base + 0.4 * max(0.0, min(1.0, quality))
    return score, f"{reason}; trend quality {quality:.2f} (cross-platform, non-repetitive)"


def _source_quality(priority: Optional[int], excerpt: str) -> tuple:
    from app.services.world_production import THIN_SOURCE_CHARS
    base = (priority / 100.0) if isinstance(priority, (int, float)) else 0.5
    reason = f"Curation priority {priority}/100" if priority is not None else "No curation score; assumed average"
    if len(excerpt or "") < THIN_SOURCE_CHARS:
        return base * 0.6, reason + "; thin source text, few facts to draw on"
    return base, reason


# Words so common in captions and encyclopedia text alike that sharing them says nothing about a
# real connection (measured: "after", "experience", "world" made unrelated pairs look perfect).
_GENERIC_WORDS = frozenset(
    "after before experience world people time year years day days new old first last life love video post real "
    "beautiful best good great big little part history today know make made many famous known called place "
    "city country national state found also used like just get got still well".split())


def _match_stems(text: str) -> set:
    """_content_stems plus a trailing-e fold: it strips "es" from "bronzes" ("bronz") but leaves
    "bronze" whole, so the two never matched."""
    from app.services.culturetoon_script import _content_stems
    return {w[:-1] if w.endswith("e") and len(w) > 4 else w for w in _content_stems(text)
            if w not in _GENERIC_WORDS and not w.isdigit()}


def _cultural_relevance(trend_text: str, source_text: str) -> tuple:
    source_stems = _match_stems(source_text)
    shared = []  # the trend's own words, in order, so the reason reads naturally
    for word in re.findall(r"[A-Za-z]+", trend_text or ""):
        if word.lower() in _GENERIC_WORDS:
            continue
        stems = _match_stems(word)
        if stems and stems <= source_stems and word.lower() not in shared:
            shared.append(word.lower())
    bonus = {0: 0.0, 1: 0.25, 2: 0.4}.get(len(shared), 0.5)
    if shared:
        return 0.5 + bonus, f"Same country; shares words with the source: {', '.join(shared[:5])}"
    return 0.5, "Same country, no shared words: the connection must come from the joke"


def _novelty(times_used: int) -> tuple:
    if times_used <= 0:
        return 1.0, "Source not used in any video or script yet"
    if times_used == 1:
        return 0.5, "Source already used once"
    return 0.2, f"Source already used {times_used} times"


def _cast_fit(region: str, cast_regions: Optional[list]) -> tuple:
    if cast_regions is None:
        return 0.4, "No cast chosen yet"
    regions = {r.upper() for r in cast_regions if r}
    if region.upper() in regions:
        return 1.0, "A cast member is from this country"
    if continent_for(region) in {continent_for(r) for r in regions}:
        return 0.6, "A cast member is from the same continent"
    if not regions:
        return 0.4, "Cast has no home countries set"
    return 0.3, "No cast member from this part of the world"


def rank_candidate(*, trend_text: str, trend_momentum: Optional[str], trend_quality: Optional[float],
                   source_text: str, source_priority: Optional[int], times_used: int, region: str,
                   cast_regions: Optional[list] = None, trend_kind: str = "cluster",
                   source_focus: Optional[str] = None) -> tuple:
    """Pure: (score 0-1, [{"factor", "score", "weight", "reason"}]). source_text is the full excerpt
    (judges how much material there is); source_focus is what the source is ABOUT (title + summary),
    the only fair thing to compare a trend with."""
    values = {
        "trend_momentum": _trend_momentum(trend_momentum, trend_quality, trend_kind),
        "source_quality": _source_quality(source_priority, source_text),
        "cultural_relevance": _cultural_relevance(trend_text, source_focus or source_text),
        "novelty": _novelty(times_used),
        "cast_fit": _cast_fit(region, cast_regions),
    }
    factors = [{"factor": name, "score": round(score, 3), "weight": RANK_WEIGHTS[name], "reason": reason}
               for name, (score, reason) in values.items()]
    total = sum(f["score"] * f["weight"] for f in factors)
    return round(total, 4), factors


def balance_slate(candidates: list) -> list:
    """Round-robin across continents (each in rank order) so one country or continent can never
    fill the top of the list on volume alone."""
    by_continent = defaultdict(list)
    for c in candidates:
        by_continent[c["continent"]].append(c)
    queues = [sorted(group, key=lambda c: c.get("rank_score") or 0, reverse=True)
              for _, group in sorted(by_continent.items(), key=lambda kv: kv[0])]
    queues.sort(key=lambda q: q[0].get("rank_score") or 0, reverse=True)
    balanced = []
    while any(queues):
        for q in queues:
            if q:
                balanced.append(q.pop(0))
    return balanced


def coverage_summary(candidates: list) -> dict:
    counts = defaultdict(int)
    for c in candidates:
        counts[c["continent"]] += 1
    return {"by_continent": {k: counts.get(k, 0) for k in (*TARGET_CONTINENTS, "Oceania", "Other")},
            "gaps": [k for k in TARGET_CONTINENTS if not counts.get(k)]}


# ── Building candidates ───────────────────────────────────────────────────────

TREND_LOOKBACK_DAYS = 7
TREND_GROUPS_PER_REGION = 5
SOURCES_PER_REGION = 8
SAFE_PER_REGION = 3
BLOCKED_SHOWN_PER_REGION = 2


def _trend_groups(session, region: str, since: datetime) -> list:
    """Recent trend signals for one country: one group per Cluster the trends belong to, plus the
    strongest unclustered single trends."""
    from app.models.trend import Trend
    from app.models.cluster import Cluster

    rows = (session.query(Trend).filter(Trend.region == region, Trend.collected_at >= since)
            .order_by(Trend.velocity_score.desc().nullslast(), Trend.likes.desc().nullslast()).limit(200).all())
    by_cluster = defaultdict(list)
    singles = []
    for t in rows:
        (by_cluster[t.cluster_id] if t.cluster_id else singles).append(t)
    clusters = {c.id: c for c in session.query(Cluster).filter(Cluster.id.in_(list(by_cluster))).all()} if by_cluster else {}

    groups = []
    for cluster_id, trends in by_cluster.items():
        cluster = clusters.get(cluster_id)
        if not cluster or not (cluster.theme or cluster.summary):
            singles.extend(trends)
            continue
        groups.append({"trend_type": "cluster", "trend_id": cluster.id, "title": cluster.theme or f"Cluster {cluster.id}",
                       "summary": cluster.summary, "momentum": cluster.momentum, "quality": cluster.quality_score,
                       "platforms": sorted({t.platform for t in trends if t.platform}), "weight": len(trends)})
    groups.sort(key=lambda g: (g["quality"] or 0, g["weight"]), reverse=True)
    for t in singles:
        text = (t.title or t.translated_content or t.content or "").strip()
        if _has_substance(text):
            groups.append({"trend_type": "trend", "trend_id": t.id, "title": text[:200],
                           "summary": (t.translated_content or t.content or "")[:600] or None, "momentum": None,
                           "quality": None, "platforms": [t.platform] if t.platform else [], "weight": 1})
    return groups[:TREND_GROUPS_PER_REGION]


MIN_CAPTION_LETTERS = 15


def _has_substance(text: str) -> bool:
    """A single post is only worth pairing if it says something: at least MIN_CAPTION_LETTERS letters
    once hashtags, mentions and links are removed (real data had "all luv #school #friends #real").
    Counts letters in any script, so Japanese, Arabic or Hindi captions are judged the same way."""
    stripped = re.sub(r"(?:https?://\S+|[#@]\S+)", " ", text or "")
    return sum(1 for ch in stripped if ch.isalpha()) >= MIN_CAPTION_LETTERS


def _pick_diverse(pairs: list, limit: int) -> list:
    """Best-first, but each trend and each source at most once, so one viral post cannot take every
    slot for a country paired with different sources."""
    chosen, trends, sources = [], set(), set()
    for pair in pairs:
        _, _, group, item = pair[:4]
        key = (group["trend_type"], group["trend_id"])
        if key in trends or item.id in sources:
            continue
        chosen.append(pair)
        trends.add(key)
        sources.add(item.id)
        if len(chosen) >= limit:
            break
    return chosen


def _usable_sources(session, region: str, now: datetime) -> list:
    from app.models.curated_item import CuratedItem
    q = session.query(CuratedItem).filter(
        CuratedItem.region == region,
        CuratedItem.source_type.in_(("wikipedia", "unesco")),
        CuratedItem.source_url.isnot(None),
        (CuratedItem.pipeline_decision == "include") | CuratedItem.pipeline_decision.is_(None),
        CuratedItem.expires_at.is_(None) | (CuratedItem.expires_at > now),
    )
    return q.order_by(CuratedItem.priority_score.desc().nullslast()).limit(SOURCES_PER_REGION).all()


def _times_used(session, item_id) -> int:
    from app.models.toon import Toon
    from app.models.editorial_candidate import EditorialCandidate
    toons = session.query(Toon.id).filter(Toon.curated_item_id == item_id).count()
    scripted = session.query(EditorialCandidate.id).filter(
        EditorialCandidate.curated_item_id == item_id, EditorialCandidate.script_id.isnot(None)).count()
    return toons + scripted


def cast_home_regions(session, brand_id) -> list:
    from app.models.character import Character
    rows = session.query(Character.home_region).filter(Character.brand_id == brand_id).all()
    return [r[0] for r in rows if r[0]]


def build_candidates(session, *, cast_regions: Optional[list] = None, days: int = TREND_LOOKBACK_DAYS,
                     now: Optional[datetime] = None) -> dict:
    """Creates new candidate rows for every country that has both recent trends and usable curated
    sources. Per country it keeps the top SAFE_PER_REGION safe pairs and shows up to
    BLOCKED_SHOWN_PER_REGION blocked ones (with their exclusion reasons). Existing pairs are never
    duplicated. Adds rows to the session; the caller commits."""
    from app.models.curated_item import CuratedItem
    from app.models.editorial_candidate import EditorialCandidate
    from app.services.world_production import build_source_facts

    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    regions = [r[0] for r in session.query(CuratedItem.region).filter(CuratedItem.region.isnot(None)).distinct().all()]
    existing = {(c.trend_type, c.trend_id, str(c.curated_item_id)) for c in
                session.query(EditorialCandidate.trend_type, EditorialCandidate.trend_id,
                              EditorialCandidate.curated_item_id).all()}

    created, skipped_regions = [], []
    for region in sorted(regions):
        groups = _trend_groups(session, region, since)
        sources = _usable_sources(session, region, now)
        if not groups or not sources:
            skipped_regions.append({"region": region, "reason": "no recent trends" if not groups else "no usable sources"})
            continue
        usage = {item.id: _times_used(session, item.id) for item in sources}
        safe, blocked = [], []
        for g in groups:
            trend_text = f"{g['title']}. {g['summary'] or ''}"
            for item in sources:
                if (g["trend_type"], g["trend_id"], str(item.id)) in existing:
                    continue
                excerpt = build_source_facts(item)
                screen = screen_safety(trend_text, f"{item.title}. {excerpt}")
                score, factors = rank_candidate(
                    trend_text=trend_text, trend_momentum=g["momentum"], trend_quality=g["quality"],
                    source_text=excerpt, source_priority=item.priority_score,
                    times_used=usage[item.id], region=region, cast_regions=cast_regions,
                    trend_kind=g["trend_type"], source_focus=f"{item.title}. {item.summary or ''}")
                (blocked if screen["exclusions"] else safe).append((score, factors, g, item, excerpt, screen))
        safe.sort(key=lambda x: x[0], reverse=True)
        blocked.sort(key=lambda x: x[0], reverse=True)
        for score, factors, g, item, excerpt, screen in (_pick_diverse(safe, SAFE_PER_REGION)
                                                          + _pick_diverse(blocked, BLOCKED_SHOWN_PER_REGION)):
            is_blocked = bool(screen["exclusions"])
            row = EditorialCandidate(
                trend_type=g["trend_type"], trend_id=g["trend_id"], trend_title=g["title"],
                trend_summary=g["summary"], trend_platforms=g["platforms"], trend_momentum=g["momentum"],
                region=region, continent=continent_for(region),
                curated_item_id=item.id, source_type=item.source_type, source_title=item.title,
                source_url=item.source_url, source_excerpt=excerpt,
                # Safety is a gate, not a weight: a blocked row is never given a score.
                rank_score=None if is_blocked else score, rank_factors=factors,
                rank_weights_version=RANK_WEIGHTS_VERSION,
                status="blocked" if is_blocked else "candidate",
                safety_status="blocked" if is_blocked else "pending",
                safety_flags=screen["exclusions"], safety_review_flags=screen["review"],
            )
            session.add(row)
            existing.add((g["trend_type"], g["trend_id"], str(item.id)))
            created.append(row)
    return {"created": created, "skipped_regions": skipped_regions}


# ── Script brief, grounding and claim provenance ──────────────────────────────


def build_script_brief(candidate, fmt: str, language: str) -> str:
    """The idea text handed to the existing cast-aware comedy writer. The source excerpt is fenced
    as the only allowed facts; the trend is explicitly context."""
    from app.collectors.region_codes import region_name
    from app.services.world_production import source_label
    return f"""EDITORIAL BRIEF: trend-to-culture comedy for viewers in {region_name(candidate.region)}.

CURRENT TREND (context for the hook only, NOT a source of facts): {candidate.trend_title}. {candidate.trend_summary or ""}

LOCAL CONNECTION: {candidate.source_title} ({source_label(candidate)})
VERIFIED SOURCE MATERIAL (the ONLY allowed source of facts):
<<<
{candidate.source_excerpt.strip()[:4000]}
>>>

FORMAT: {EDITORIAL_FORMATS[fmt]}

RULES:
- Every date, number, name, place or historical claim must come from the VERIFIED SOURCE MATERIAL. Do not state facts from the trend or from general knowledge.
- The joke is in the contrast, the timing or the characters' reactions. Never change or exaggerate a fact.
- No culture, nationality or ethnicity is the punchline. Do not mock real, named people. Do not joke about tragedy, war or religious worship.
- Write all dialogue in {LANGUAGES[language]}."""


def _split_sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if len(s.strip()) > 20]


def _claim_in_line(claim: str, line: str) -> bool:
    a, b = claim.strip().strip('"').lower(), (line or "").lower()
    return bool(a) and (a in b or (len(b) > 10 and b in a))


def link_claims_to_source(script_result: dict, source_excerpt: str, unsupported: list) -> list:
    """One entry per spoken line (hook first): the source sentence that best supports it, if any,
    and whether the fact-checker flagged it. A line with no matching sentence is not an error on its
    own (most comedy lines state no fact); a flagged line is."""
    from app.services.culturetoon_script import _content_stems, claim_supported_by_source
    sentences = [(s, set(_content_stems(s))) for s in _split_sentences(source_excerpt)]
    lines = [(None, script_result.get("hook_line") or "")]
    lines += [(shot.get("shot_number"), (shot.get("dialogue") or "").strip()) for shot in script_result.get("shots") or []]
    linked = []
    for shot_number, text in lines:
        if not text:
            continue
        stems = set(_content_stems(text))
        best, best_overlap = None, 0.0
        for sentence, sentence_stems in sentences:
            overlap = len(stems & sentence_stems) / len(stems) if stems else 0.0
            if overlap > best_overlap:
                best, best_overlap = sentence, overlap
        flagged = [c for c in unsupported if _claim_in_line(c, text)]
        linked.append({
            "shot_number": shot_number, "text": text,
            "source_sentence": best if best_overlap >= 0.3 or (best and claim_supported_by_source(text, best)) else None,
            "flagged_claims": flagged, "supported": not flagged,
        })
    return linked


def ground_script(script_result: dict, source_excerpt: str) -> tuple:
    """(possibly-fixed script, grounding). Runs the World fact-checker against the source excerpt
    only, and one narrow claim fix if it flags anything (same tools as World production)."""
    from app.services.culturetoon_script import judge_world_grounding, fix_unsupported_claims
    grounding = judge_world_grounding(script_result, source_excerpt)
    if grounding.get("unsupported_claims") and not grounding.get("judge_failed"):
        fixed = fix_unsupported_claims(script_result, grounding["unsupported_claims"], source_excerpt)
        if fixed:
            regrounded = judge_world_grounding(fixed, source_excerpt)
            if not regrounded.get("judge_failed") and len(regrounded.get("unsupported_claims") or []) < len(grounding["unsupported_claims"]):
                script_result, grounding = fixed, {**regrounded, "auto_fixed": True}
    grounding["claims"] = link_claims_to_source(script_result, source_excerpt, grounding.get("unsupported_claims") or [])
    return script_result, grounding


def grounding_status(grounding: Optional[dict]) -> str:
    if not grounding or grounding.get("judge_failed") or grounding.get("grounded") is None:
        return "unchecked"
    return "grounded" if grounding.get("grounded") else "unsupported"


def script_fingerprint(script) -> str:
    payload = {"hook": script.hook_line or "", "shots": [
        {"dialogue": s.get("dialogue"), "action": s.get("action"), "speaker": s.get("speaker_variant_id")}
        for s in (script.shots or [])]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ── The gate ──────────────────────────────────────────────────────────────────


def editorial_gate(session, script_id) -> Optional[str]:
    """None when a script may be rendered/published, else the reason it may not. Scripts that did
    not come from this workflow are not affected. Called by every render/publish path: the
    Generate video and Publish routes and the scheduled batch renderer."""
    from app.models.editorial_candidate import EditorialCandidate
    from app.models.toon_script import ToonScript
    if not script_id:
        return None
    candidate = (session.query(EditorialCandidate).filter(EditorialCandidate.script_id == script_id)
                 .order_by(EditorialCandidate.updated_at.desc()).first())
    if candidate is None:
        return None
    if candidate.status in ("blocked", "rejected"):
        return f"Editorial candidate is {candidate.status}; it cannot be rendered or published."
    if candidate.safety_status != "cleared":
        return "Editorial safety review is not cleared yet."
    if candidate.grounding_status != "grounded":
        return "The script's factual claims are not grounded in the source yet."
    if candidate.status not in ("approved", "published"):
        return "The editorial candidate has not been approved yet."
    script = session.query(ToonScript).filter_by(id=script_id).first()
    if script is not None and candidate.approved_script_fingerprint != script_fingerprint(script):
        return "The script changed after approval. Re-check grounding and approve it again."
    return None


# ── Learning view ─────────────────────────────────────────────────────────────

MIN_POSTS_FOR_COMPARISON = 3


def _per_thousand(part: int, views: int) -> Optional[float]:
    return round(part * 1000.0 / views, 2) if views else None


def performance_rows(session) -> dict:
    """Every recorded post for an editorial video with the dimensions the brief asks to learn from,
    plus rates per 1,000 views grouped by continent, format, platform and language. Groups with
    fewer than MIN_POSTS_FOR_COMPARISON posts are marked as not enough data: these are directional
    signals from a small sample, never proof."""
    from app.models.editorial_candidate import EditorialCandidate
    from app.models.toon_post import ToonPost
    from app.models.toon_script import ToonScript

    rows = []
    q = (session.query(EditorialCandidate, ToonPost, ToonScript)
         .join(ToonPost, ToonPost.toon_id == EditorialCandidate.toon_id)
         .outerjoin(ToonScript, ToonScript.id == EditorialCandidate.script_id)
         .filter(EditorialCandidate.toon_id.isnot(None)))
    for cand, post, script in q.all():
        extra = post.extra_metrics or {}
        views = post.latest_views or 0
        rows.append({
            "candidate_id": str(cand.id), "post_id": str(post.id), "platform": post.platform,
            "post_url": post.post_url, "posted_at": post.posted_at.isoformat() if post.posted_at else None,
            "region": cand.region, "continent": cand.continent, "language": cand.language, "format": cand.format,
            "trend_type": cand.trend_type, "trend_id": cand.trend_id, "trend_title": cand.trend_title,
            "curated_item_id": str(cand.curated_item_id), "source_title": cand.source_title,
            "hook": script.hook_line if script else None, "tone": script.tone if script else None,
            "duration_seconds": script.total_duration_seconds if script else None,
            "cast": list(script.character_variant_ids or []) if script else [],
            "views": post.latest_views, "likes": post.latest_likes, "comments": post.latest_comments,
            "shares": post.latest_shares, "saves": extra.get("saves"), "follows": extra.get("follows"),
            "avg_watch_seconds": extra.get("avg_watch_seconds"), "completion_rate": extra.get("completion_rate"),
            "comments_per_1k": _per_thousand(post.latest_comments or 0, views),
            "shares_per_1k": _per_thousand(post.latest_shares or 0, views),
            "saves_per_1k": _per_thousand(extra["saves"], views) if extra.get("saves") is not None else None,
            "follows_per_1k": _per_thousand(extra["follows"], views) if extra.get("follows") is not None else None,
            "last_fetched_at": post.last_fetched_at.isoformat() if post.last_fetched_at else None,
        })

    groups = {}
    for dimension in ("continent", "format", "platform", "language"):
        buckets = defaultdict(list)
        for r in rows:
            buckets[r[dimension] or "unknown"].append(r)
        groups[dimension] = []
        for key, members in sorted(buckets.items()):
            views = sum(m["views"] or 0 for m in members)
            groups[dimension].append({
                "value": key, "posts": len(members), "views": views,
                "comments_per_1k": _per_thousand(sum(m["comments"] or 0 for m in members), views),
                "shares_per_1k": _per_thousand(sum(m["shares"] or 0 for m in members), views),
                "enough_data": len(members) >= MIN_POSTS_FOR_COMPARISON,
            })
    return {"rows": rows, "groups": groups, "min_posts_for_comparison": MIN_POSTS_FOR_COMPARISON}
