"""
Agent 4 — Content Strategist
Uses Qwen-max (via Alibaba Dashscope) to generate personalized content ideas per user.
Falls back to Claude if Qwen is unavailable.
"""
import json
import logging
import os
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.content_strategist")


def _get_qwen_client():
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["QWEN_API_KEY"],
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def _get_claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _generate_ideas_qwen(profile: dict, clusters: list[dict]) -> list[dict]:
    qwen = _get_qwen_client()
    prompt = _build_prompt(profile, clusters)
    response = qwen.chat.completions.create(
        model="qwen-max",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return _parse_ideas(response.choices[0].message.content)


def _generate_ideas_claude(profile: dict, clusters: list[dict]) -> list[dict]:
    client = _get_claude_client()
    prompt = _build_prompt(profile, clusters)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_ideas(message.content[0].text)


def _build_prompt(profile: dict, clusters: list[dict]) -> str:
    niche = profile.get("industry_niche") or "general brand"
    platforms = ", ".join(profile.get("target_platforms") or ["TikTok", "Instagram"])
    tones = ", ".join(profile.get("content_tones") or ["authentic"])
    goals = ", ".join(profile.get("content_goals") or ["brand awareness"])
    tags = ", ".join(profile.get("persona_tags") or [])
    age_min = profile.get("target_age_min") or 18
    age_max = profile.get("target_age_max") or 35

    cluster_summary = json.dumps(
        [{"name": c.get("name"), "description": c.get("description"), "emotional_theme": c.get("emotional_theme")}
         for c in (clusters or [])[:6]],
        ensure_ascii=False,
    )

    return f"""You are an expert content strategist for {niche}.

Target audience:
- Age: {age_min}–{age_max}
- Platforms: {platforms}
- Tone: {tones}
- Goals: {goals}
- Persona types: {tags or "general audience"}

Today's trending cultural signals (summarized):
{cluster_summary}

Generate exactly 10 content ideas that tap into these trends.
Each idea must be tailored specifically to the brand's niche, tone, and audience.

Return ONLY a valid JSON array with exactly 10 objects. Each object must have these exact keys:
- hook: attention-grabbing opening line or video hook (max 15 words)
- caption: full post caption with 3-5 relevant hashtags (50-100 words)
- cta: clear call to action (max 10 words)
- music_mood: background music style for TikTok/Reels (e.g. "Dark hypnotic trap", "Upbeat indie pop")
- platform: best platform for this specific idea
- trend_connection: which trend this taps into and why it works (max 20 words)
- format: content format (e.g. "short video", "carousel", "talking head", "GRWM", "duet")

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

        ideas = []
        try:
            if os.getenv("QWEN_API_KEY"):
                ideas = _generate_ideas_qwen(profile, clusters)
            else:
                ideas = _generate_ideas_claude(profile, clusters)
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
