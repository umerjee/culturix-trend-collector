"""
Trend & content validation — an AI gate that reviews proposed trend clusters
and generated content ideas before they're used/shown, checking:
  - legitimate: does the cluster genuinely match its example posts, or is it
    a clustering hallucination?
  - safe: is this appropriate to build content around (no hate speech,
    extremism, illegal activity, highly inflammatory politics)?
  - durability (clusters only): "sustained" (ongoing cultural/fandom
    interest) vs "spike" (tied to one dated event, e.g. a specific match/
    election/awards show) vs "unclear".

Filtering policy: legitimacy/safety are hard gates (rejected clusters/ideas
are dropped). Durability is a soft tag, not a hard filter — a "spike" isn't
unsafe or fake, and some profiles legitimately want timely/newsjacking
content; the tag lets content_strategist phrase it appropriately instead of
blanket-blocking it platform-wide.

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

Review these {len(payload)} candidate trend clusters, each identified by an AI from real social media posts. For EACH cluster, assess:
1. legitimate (bool): does the theme/description genuinely and coherently match the example posts? (false = hallucinated or incoherent grouping)
2. safe (bool): is this an appropriate topic to build brand/creator content around? (false = hate speech, extremism, illegal activity, graphic violence, highly inflammatory politics)
3. durability ("sustained" | "spike" | "unclear"): is this an ongoing cultural/fandom/lifestyle interest likely still relevant in a few weeks ("sustained"), or tied to one specific dated event like a single match/election/awards show/holiday that loses relevance almost immediately after ("spike")? Use "unclear" if genuinely ambiguous.

Clusters:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY a JSON array, one object per cluster IN THE SAME ORDER, each with exactly these keys:
{{"legitimate": bool, "safe": bool, "durability": "sustained"|"spike"|"unclear", "reason": "<one sentence>"}}"""

    return _parse_json_array(_call_validation_llm(prompt))


def _validate_ideas_via_llm(ideas: list) -> list:
    payload = [
        {"hook": i.get("hook", ""), "caption": i.get("caption", ""), "cta": i.get("cta", ""),
         "trend_connection": i.get("trend_connection", "")}
        for i in ideas
    ]
    prompt = f"""You are a content moderation and quality reviewer for a social media content-idea generator.

Review these {len(payload)} generated content ideas for a brand/creator profile. For EACH idea, assess:
1. safe (bool): is this appropriate/brand-safe to post publicly? (false = hate speech, harassment, illegal activity encouragement, impersonation, misleading claims)
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
