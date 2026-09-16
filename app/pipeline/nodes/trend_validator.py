"""
Trend & content validation — an AI gate that reviews proposed trend clusters
and generated content ideas before they're used/shown, checking:
  - legitimate: does the cluster genuinely match its example posts, or is it
    a clustering hallucination?
  - safe: is this appropriate to build content around (hard gate: hate
    speech, harassment, extremism, incitement/glorification of violence,
    illegal activity, graphic violence, or fabricated claims presented as
    fact — NOT merely being about politics, protests, immigration, gender,
    sexual orientation, or other real, currently-trending social topics;
    see the 2026-07-24 recalibration note below)
  - durability (clusters only): "sustained" (ongoing cultural/fandom
    interest) vs "spike" (tied to one dated event, e.g. a specific match/
    election/awards show) vs "unclear".

Filtering policy: legitimacy/safety are hard gates (rejected clusters/ideas
are dropped). Durability is a soft tag, not a hard filter — a "spike" isn't
unsafe or fake, and some profiles legitimately want timely/newsjacking
content; the tag lets content_strategist phrase it appropriately instead of
blanket-blocking it platform-wide.

Recalibrated 2026-07-24: an audit of trend_validation_log found the "safe"
gate was over-rejecting — real, mainstream trending topics (student
protests, immigration-policy debate, gender/dating discourse, geopolitical
news) were being marked unsafe purely for being political/social/divisive,
not for containing actual hate speech or incitement. Real trending topics
covering social issues, politics, or sexual orientation are not themselves
a safety problem and must not be filtered out just for being sensitive —
the prompts below were narrowed to only hard-gate genuine hate
speech/extremism/incitement/illegal activity/graphic violence/fabricated-
as-fact claims, not "divisive" or "controversial" topics in general.

Recalibrated again 2026-09-16: a second audit (162/500 = 32% rejection
rate) found the "fabricated/unverifiable factual claim" language, on its
own, produces a systematic false-positive class: the validation LLM has no
web access and only its static training data, so it cannot actually verify
recent real-world claims -- and this pipeline's whole purpose is surfacing
CURRENT/recent trends (a 2027 tour announcement, a same-week reality-show
elimination), which by construction skew recent/past-cutoff. Real examples
pulled straight from trend_validation_log: "Harry Styles 2027 Tour... no
public record of an official tour announcement", "Koh-Lanta All Stars...
no verifiable recent episode featuring Lola's elimination" -- both
plausible, specific, real-person/real-show claims rejected purely because
the model didn't personally recognize them, not because anything about
them was internally inconsistent or impossible. The clusters/ideas here
are already sourced from real, live posts this platform's own collectors
pulled (Reddit/TikTok/YouTube/Twitter/Xiaohongshu/Google Trends) -- that
source data is inherently more current than the validator LLM's frozen
knowledge, so "I don't recognize this" must not be treated as evidence of
fabrication. The prompts below now scope the fabrication check to
INTERNAL coherence (does the claim match/follow from the provided
description or example posts, or is it self-contradictory/impossible) --
not independent fact-checking against the model's own memory. A second
pass (_double_check_rejections) also now re-examines any rejection whose
stated reason reads as "I can't verify/recognize this" before it's
finalized, explicitly challenging the model to distinguish "impossible or
incoherent" from "just unfamiliar or recent" -- this is what "double
check itself before rejecting" means in the code below.

Fail-open: if the validation call itself fails, skip filtering and log a
warning — a validation outage must never take down the whole daily pipeline.

Every result (kept or dropped) is logged to trend_validation_log for audit.
"""
import json
import logging
import os

from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.trend_validator")


def _get_deepseek():
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )


def _call_validation_llm(prompt: str) -> str:
    """DeepSeek first, falls back to Claude Haiku — same resilience pattern
    used elsewhere in this pipeline (clusterer.py, content_check.py)."""
    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            deepseek = _get_deepseek()
            response = deepseek.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("DeepSeek validation call failed, falling back to Claude: %s", e)

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _parse_json_array(raw: str) -> list:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _log_validation(source: str, subject: str, legitimate, safe, durability, status: str, reason: str):
    try:
        from app.db import SessionLocal
        from app.models.trend_validation_log import TrendValidationLog

        session = SessionLocal()
        try:
            session.add(TrendValidationLog(
                source=source,
                subject=(subject or "(untitled)")[:2000],
                legitimate=legitimate,
                safe=safe,
                durability=durability,
                status=status,
                reason=reason,
            ))
            session.commit()
        finally:
            session.close()
    except Exception as e:
        logger.warning("Failed to write validation log row: %s", e)


def _validate_clusters_via_llm(clusters: list) -> list:
    payload = [
        {
            "name": c.get("name", ""),
            "description": c.get("description", ""),
            "emotional_theme": c.get("emotional_theme", ""),
            "example_posts": (c.get("example_posts") or [])[:3],
        }
        for c in clusters
    ]
    prompt = f"""You are a content moderation and quality-assurance reviewer for a trend-intelligence platform.

These {len(payload)} candidate trend clusters were identified by an AI from REAL social media posts, scraped live by this platform's own collectors (Reddit/TikTok/YouTube/Twitter/Xiaohongshu/Google Trends). You do NOT have web access and your knowledge has a training cutoff — this pipeline exists specifically to surface CURRENT/recent trends, so many genuinely real clusters will describe events, announcements, or people you don't personally recognize. That is expected and normal, NOT evidence of fabrication.

For EACH cluster, assess:
1. legitimate (bool): does the theme/description genuinely and coherently match the example posts, and is it internally plausible (not self-contradictory or logically impossible)? false = hallucinated/incoherent grouping that doesn't match its own example posts, OR a claim that is internally impossible or self-contradictory. Do NOT mark false just because you personally don't recognize the person/event/show or can't independently confirm it happened — recency past your training cutoff is not fabrication. If the claim is plausible, specific, and consistent with the example posts, treat it as legitimate even if unfamiliar.
2. safe (bool): mark false ONLY for genuine hate speech targeting a protected group, harassment, extremism, incitement or glorification of violence, illegal activity, or graphic/gratuitous violence. Being about politics, protests, immigration policy, gender, sexual orientation, war/geopolitics, or other real, currently-trending social issues is NOT by itself unsafe — these are legitimate news and cultural topics that real creators and brands do cover, and a topic being divisive, polarizing, or emotionally charged is not a reason to reject it. Only reject for the actual presence of hateful, violent, illegal, or extremist content — not for the subject matter being political or sensitive.
3. durability ("sustained" | "spike" | "unclear"): is this an ongoing cultural/fandom/lifestyle interest likely still relevant in a few weeks ("sustained"), or tied to one specific dated event like a single match/election/awards show/holiday that loses relevance almost immediately after ("spike")? Use "unclear" if genuinely ambiguous.

Clusters:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY a JSON array, one object per cluster IN THE SAME ORDER, each with exactly these keys:
{{"legitimate": bool, "safe": bool, "durability": "sustained"|"spike"|"unclear", "reason": "<one sentence>"}}"""

    return _parse_json_array(_call_validation_llm(prompt))


_UNVERIFIABLE_REASON_MARKERS = (
    "cannot be verified", "can not be verified", "can't be verified", "cannot confirm",
    "can't confirm", "impossible to confirm", "unable to confirm",
    "no public record", "no record of", "no confirmed", "not confirmed",
    "unable to verify", "no evidence", "could not find", "not aware of",
    "no official", "unverified", "fabricat", "no verifiable", "does not appear to",
    "not currently possible to verify", "cannot verify", "can't verify",
)


def _looks_unverifiable_reason(reason: str) -> bool:
    """Heuristic: does a rejection reason read as 'I personally don't
    recognize/can't confirm this' rather than 'this is internally
    incoherent or impossible'? These are exactly the false-positive class
    a fail-closed, non-web-connected LLM produces on recent real trends —
    see the 2026-09-16 recalibration note at the top of this file."""
    r = (reason or "").lower()
    return any(marker in r for marker in _UNVERIFIABLE_REASON_MARKERS)


def _double_check_rejections(items: list, results: list, reject_field: str, item_to_payload) -> list:
    """Second pass, ONLY for items rejected on unverifiability-flavored
    reasoning: re-examines them with an explicit challenge to distinguish
    genuine incoherence/impossibility from mere unfamiliarity, before the
    rejection is finalized. Bounded cost -- most items are approved on the
    first pass and never reach this function's LLM call at all."""
    to_recheck = [
        (i, item, r) for i, (item, r) in enumerate(zip(items, results))
        if not bool(r.get(reject_field, True)) and _looks_unverifiable_reason(r.get("reason", ""))
    ]
    if not to_recheck:
        return results

    payload = [
        {**item_to_payload(item), "original_rejection_reason": r.get("reason", "")}
        for _, item, r in to_recheck
    ]
    prompt = f"""You are double-checking {len(payload)} items that were just REJECTED by a first-pass content reviewer, specifically because that reviewer said it could not verify or did not recognize the claim.

That first-pass reviewer has NO web access and only static training data with a cutoff date. This platform surfaces CURRENT/recent real trends scraped live from social media, so "I don't recognize this" is expected for genuinely real, recent items and must NOT by itself justify rejection.

For EACH item, decide: was the original rejection actually justified?
- Overturn the rejection (approved: true) if the claim is plausible, specific, and internally consistent — even if it names a recent event/announcement/person/show you don't personally recognize either. Being unfamiliar or recent is NOT grounds to keep it rejected.
- Keep the rejection (approved: false) ONLY if the claim is genuinely self-contradictory, logically impossible, or an obvious/well-known hoax you have high confidence is false — not merely "unconfirmed."

Items:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY a JSON array, one object per item IN THE SAME ORDER, each with exactly these keys:
{{"approved": bool, "reason": "<one sentence>"}}"""

    try:
        rechecked = _parse_json_array(_call_validation_llm(prompt))
    except Exception as e:
        logger.warning("Double-check pass failed, keeping original rejections: %s", e)
        return results
    if len(rechecked) != len(to_recheck):
        logger.warning(
            "Double-check result count mismatch (%d vs %d), keeping original rejections",
            len(rechecked), len(to_recheck),
        )
        return results

    reversed_count = 0
    for (i, _item, r), new in zip(to_recheck, rechecked):
        if bool(new.get("approved", False)):
            results[i] = {**r, reject_field: True, "reason": f"(double-check reversed original rejection: {r.get('reason', '')}) {new.get('reason', '')}"}
            reversed_count += 1
    if reversed_count:
        logger.info("Double-check reversed %d/%d unverifiability-flavored rejections", reversed_count, len(to_recheck))
    return results


def _validate_ideas_via_llm(ideas: list) -> list:
    payload = [
        {"hook": i.get("hook", ""), "caption": i.get("caption", ""), "cta": i.get("cta", ""),
         "trend_connection": i.get("trend_connection", "")}
        for i in ideas
    ]
    prompt = f"""You are a content moderation and quality reviewer for a social media content-idea generator.

These ideas are generated FROM real trending topics that this platform's own collectors scraped live from social media (Reddit/TikTok/YouTube/Twitter/Xiaohongshu/Google Trends). You do NOT have web access and your knowledge has a training cutoff — many genuinely real ideas will reference recent events/announcements/people you don't personally recognize. That is expected, NOT evidence the claim is fabricated.

Review these {len(payload)} generated content ideas for a brand/creator profile. For EACH idea, assess:
1. safe (bool): mark false ONLY for genuine hate speech, harassment, illegal activity encouragement, impersonation, or a claim that is internally self-contradictory/impossible or a well-known hoax you have high confidence is false. Do NOT mark false just because you personally don't recognize or can't independently confirm the specific event/announcement — recency past your training cutoff is not fabrication. Covering a real trending political, social, or sexual-orientation/identity topic is NOT by itself unsafe — these are legitimate topics real creators post about; do not reject an idea merely for touching a sensitive or divisive subject.
2. coherent (bool): does the idea make basic sense as a real, postable piece of content (not garbled/nonsensical)?
3. specific (bool): does the hook/caption/trend_connection name an actual real, concrete
   entity — a real person's name, a real movie/show title, a real event, a real product —
   that the trend is about? false = generic template filler with no real referent, e.g.
   "this celebrity feud", "a movie reboot", "the drama", "this trend" without ever saying
   who or what it actually is. A reader who has never heard of the trend should be able to
   tell from the text alone what specific real thing it's about.

Ideas:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY a JSON array, one object per idea IN THE SAME ORDER, each with exactly these keys:
{{"safe": bool, "coherent": bool, "specific": bool, "reason": "<one sentence>"}}"""

    return _parse_json_array(_call_validation_llm(prompt))


def validate_clusters(state: PipelineState) -> PipelineState:
    """Gates state['clusters'] (the ephemeral trend clusters that feed
    map_personas -> content_strategist) before they can influence content."""
    clusters = state.get("clusters", [])
    if not clusters:
        return state

    try:
        results = _validate_clusters_via_llm(clusters)
    except Exception as e:
        logger.warning("Cluster validation failed — fail-open, keeping all clusters: %s", e)
        state["errors"] = state.get("errors", []) + [f"validate_clusters: {e}"]
        return state

    if len(results) != len(clusters):
        logger.warning(
            "Cluster validation result count mismatch (%d results vs %d clusters) — fail-open",
            len(results), len(clusters),
        )
        return state

    results = _double_check_rejections(
        clusters, results, "legitimate",
        lambda c: {"name": c.get("name", ""), "description": c.get("description", ""),
                   "example_posts": (c.get("example_posts") or [])[:3]},
    )

    kept = []
    for cluster, result in zip(clusters, results):
        legitimate = bool(result.get("legitimate", True))
        safe = bool(result.get("safe", True))
        durability = result.get("durability", "unclear")
        reason = result.get("reason", "")
        status = "approved" if (legitimate and safe) else "rejected"

        _log_validation("cluster", cluster.get("name", ""), legitimate, safe, durability, status, reason)

        if status == "approved":
            cluster["durability"] = durability  # soft-tag, passed through — not a filter
            kept.append(cluster)
        else:
            logger.info(
                "Cluster rejected: %r (legitimate=%s safe=%s reason=%s)",
                cluster.get("name"), legitimate, safe, reason,
            )

    logger.info("Cluster validation: %d/%d approved", len(kept), len(clusters))
    state["clusters"] = kept
    return state


def validate_ideas(state: PipelineState) -> PipelineState:
    """Gates each profile's generated ideas before write_digests persists/emails
    them. Durability doesn't apply at this level — that's handled upstream at
    the cluster stage; this is a final safety/coherence check on the actual
    generated text."""
    results_list = state.get("generated_content", [])
    if not results_list:
        return state

    for entry in results_list:
        ideas = entry.get("ideas", [])
        if not ideas:
            continue

        try:
            validations = _validate_ideas_via_llm(ideas)
        except Exception as e:
            logger.warning(
                "Idea validation failed for user %s — fail-open, keeping all ideas: %s",
                entry.get("user_id"), e,
            )
            continue

        if len(validations) != len(ideas):
            logger.warning(
                "Idea validation result count mismatch for user %s — fail-open",
                entry.get("user_id"),
            )
            continue

        validations = _double_check_rejections(
            ideas, validations, "safe",
            lambda i: {"hook": i.get("hook", ""), "caption": i.get("caption", ""),
                       "cta": i.get("cta", ""), "trend_connection": i.get("trend_connection", "")},
        )

        kept_ideas = []
        for idea, v in zip(ideas, validations):
            safe = bool(v.get("safe", True))
            coherent = bool(v.get("coherent", True))
            specific = bool(v.get("specific", True))
            reason = v.get("reason", "")
            status = "approved" if (safe and coherent and specific) else "rejected"

            _log_validation("idea", idea.get("hook", ""), None, safe, None, status, reason)

            if status == "approved":
                kept_ideas.append(idea)
            else:
                logger.info(
                    "Idea rejected: %r (safe=%s coherent=%s specific=%s reason=%s)",
                    idea.get("hook"), safe, coherent, specific, reason,
                )

        entry["ideas"] = kept_ideas

    return state
