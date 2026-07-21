"""
Agent 4 — Content Strategist
Uses Qwen-max (via Alibaba Dashscope) to generate personalized content ideas per user.
Falls back to Claude if Qwen is unavailable.
"""
import json
import logging
import os
from typing import Optional
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.content_strategist")


def _get_qwen_client():
    # Dashscope has two separate regional deployments (China: dashscope.aliyuncs.com,
    # International: dashscope-intl.aliyuncs.com) with non-interchangeable API keys.
    # This account's key is provisioned on the international side — confirmed live
    # against dashscope.aliyuncs.com (401 InvalidApiKey) vs dashscope-intl.aliyuncs.com
    # (succeeds) before making this the default.
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["QWEN_API_KEY"],
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )


def _get_claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _generate_ideas_qwen(profile: dict, clusters: list[dict], top_signals: list[dict]) -> list[dict]:
    qwen = _get_qwen_client()
    prompt = _build_prompt(profile, clusters, top_signals)
    response = qwen.chat.completions.create(
        model="qwen-max",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return _parse_ideas(response.choices[0].message.content)


def _generate_ideas_claude(profile: dict, clusters: list[dict], top_signals: list[dict]) -> list[dict]:
    client = _get_claude_client()
    prompt = _build_prompt(profile, clusters, top_signals)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_ideas(message.content[0].text)


_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _history_note(cluster: dict) -> str:
    """Renders the recurrence context trend_historian.py attaches to cluster['history']
    into a short phrase the prompt can use to ground ideas in real pattern data
    (e.g. an actual weekly Friday spike) instead of treating every trend as brand new."""
    history = cluster.get("history")
    if not history:
        return "first time we've seen this trend, no history yet"

    count = history.get("occurrence_count") or 1
    pattern = history.get("recurrence_pattern") or "unclear"
    dominant_day = history.get("dominant_day_of_week")

    if pattern == "weekly" and dominant_day is not None:
        return f"seen {count} times before, recurs weekly (usually {_WEEKDAY_NAMES[dominant_day]})"
    if pattern == "yearly":
        return f"seen {count} times before, recurs yearly around this time of year"
    if pattern == "sustained":
        return f"seen {count} times before, an ongoing/sustained interest"
    if pattern == "spike":
        return f"seen {count} time(s) before, tied to a one-off event — likely a short-lived spike"
    return f"seen {count} time(s) before, pattern still unclear"


def _build_prompt(profile: dict, clusters: list[dict], top_signals: Optional[list[dict]] = None) -> str:
    niche = profile.get("industry_niche") or "general brand"
    platforms = ", ".join(profile.get("target_platforms") or ["TikTok", "Instagram"])
    tones = ", ".join(profile.get("content_tones") or ["authentic"])
    goals = ", ".join(profile.get("content_goals") or ["brand awareness"])
    tags = ", ".join(profile.get("persona_tags") or [])
    age_min = profile.get("target_age_min") or 18
    age_max = profile.get("target_age_max") or 35

    cluster_summary = json.dumps(
        [{"name": c.get("name"), "description": c.get("description"), "emotional_theme": c.get("emotional_theme"),
          "history": _history_note(c)}
         for c in (clusters or [])[:6]],
        ensure_ascii=False,
    )

    # top_signals is the actual RAG result — real posts retrieved via semantic
    # search against this specific profile's niche/tags/platforms, not the
    # same generic cluster list every profile gets. Ground the prompt in these
    # when available so content is genuinely personalized, not just themed.
    signal_texts = [
        s.get("text", "").strip()
        for s in (top_signals or [])
        if s.get("text", "").strip()
    ][:8]
    signals_section = (
        f"\nSpecific posts trending right now that match this exact audience "
        f"(retrieved via semantic search on their niche/tone/platforms):\n"
        f"{json.dumps(signal_texts, ensure_ascii=False)}\n"
        if signal_texts else ""
    )

    return f"""You are an expert content strategist for {niche}.

Target audience:
- Age: {age_min}–{age_max}
- Platforms: {platforms}
- Tone: {tones}
- Goals: {goals}
- Persona types: {tags or "general audience"}

Today's trending cultural signals (summarized, each with its "history" — how often
and in what pattern we've observed it before):
{cluster_summary}
{signals_section}
Generate exactly 10 content ideas that tap into these trends.
Where a trend's history shows a real recurring pattern (e.g. "recurs weekly, usually
Friday" or "recurs yearly"), lean into that in posting_time/trend_connection instead
of treating it as a one-off — e.g. timing the post ahead of a known recurring spike.
Treat "likely a short-lived spike" trends as timely/newsjacking, not evergreen.
Each idea must be tailored specifically to the brand's niche, tone, and audience.
{"Prefer ideas that connect to the specific posts above where relevant — they're what this exact audience is engaging with right now, not just the general theme." if signal_texts else ""}

Return ONLY a valid JSON array with exactly 10 objects. Each object must have these exact keys:
- hook: attention-grabbing opening line or video hook (max 15 words)
- caption: full post caption with 3-5 relevant hashtags (50-100 words)
- cta: clear call to action (max 10 words)
- music_mood: background music style for TikTok/Reels (e.g. "Dark hypnotic trap", "Upbeat indie pop")
- platform: best platform for this specific idea
- trend_connection: which trend this taps into and why it works (max 20 words)
- format: content format (e.g. "short video", "carousel", "talking head", "GRWM", "duet")
- video_prompt: cinematic scene description for AI video generation — subject, setting, camera movement, lighting, visual style (max 40 words)
- viral_angle: the specific viral mechanism that makes this shareable — e.g. "hot take", "myth-bust", "POV", "transformation", "duet bait", "challenge", "reaction" (max 12 words)
- posting_time: optimal day + time with one-line reasoning (e.g. "Thursday 6–8 PM EST — peak Gen Z scroll window")
- hashtag_strategy: exactly 5 hashtags mixing broad reach + niche community, space-separated (e.g. "#quietluxury #ootd #slowfashion #aestheticlife #outfitinspo")

Return ONLY the JSON array, no other text."""


def _parse_ideas(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_content(state: PipelineState) -> PipelineState:
    matches = state.get("persona_matches", [])
    if not matches:
        logger.warning("No persona matches — skipping content generation")
        state["generated_content"] = []
        return state

    results = []
    for match in matches:
        user_id = match["user_id"]
        profile = match["profile"]
        clusters = match.get("clusters", [])
        top_signals = match.get("top_signals", [])

        ideas = []
        try:
            if os.getenv("QWEN_API_KEY"):
                ideas = _generate_ideas_qwen(profile, clusters, top_signals)
            else:
                ideas = _generate_ideas_claude(profile, clusters, top_signals)
            logger.info("Generated %d ideas for user %s", len(ideas), user_id)
        except Exception as e:
            logger.error("Content generation failed for user %s: %s", user_id, e)
            state["errors"] = state.get("errors", []) + [f"content_gen:{user_id}:{e}"]
            continue

        results.append({
            "user_id": user_id,
            "content_profile_id": profile.get("content_profile_id"),
            "ideas": ideas,
            "clusters": clusters,
        })

    state["generated_content"] = results
    return state
