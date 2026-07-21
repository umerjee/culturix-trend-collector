"""Account-setup suggestions — helps a user pick a platform and a name/handle
for a NEW dedicated "avatar account" for one niche, before they go create it.

Not a LangGraph pipeline node (mirrors app/personas.py's precedent: a
self-contained AI feature reached directly by its own route, not via
app/pipeline/graph.py). Reuses content_strategist.py's Qwen/Claude client
pair rather than duplicating client construction — same creative-generation
task shape as idea generation, just a different prompt/output schema.
Results are ephemeral (never persisted) — regenerate on demand, no
idempotency/dedup needed.
"""
import json
import logging
import os
from app.pipeline.nodes.content_strategist import _get_qwen_client, _get_claude_client

logger = logging.getLogger("culturix.account_suggestions")


def _build_prompt(profile: dict) -> str:
    niche = profile.get("industry_niche") or "general content"
    platforms = ", ".join(profile.get("target_platforms") or []) or "no specific platform chosen yet"
    tones = ", ".join(profile.get("content_tones") or ["authentic"])
    goals = ", ".join(profile.get("content_goals") or ["brand awareness"])
    tags = ", ".join(profile.get("persona_tags") or []) or "general audience"

    return f"""You are a social media strategist helping someone set up a brand NEW, dedicated
social media account for this niche — they haven't created the account yet and want your
recommendation before they do.

Niche: {niche}
Platforms they're considering: {platforms}
Tone: {tones}
Goals: {goals}
Persona/audience types: {tags}

Return ONLY a valid JSON object with these exact keys:
- recommended_platforms: array of 1-3 objects {{"platform": string, "reason": string (max 20 words)}} —
  the best platform(s) for this specific niche, ranked best first. If "Platforms they're considering"
  lists any, prefer picking from those; otherwise recommend based on general platform fit for this niche.
- name_suggestions: array of 6-8 objects {{"name": string, "reason": string (max 15 words)}} — candidate
  account names/handles for this niche. Make them specific and memorable, not generic template phrasing
  like "{niche} Daily" or "{niche} Hub". Avoid anything likely to already be a registered trademark or
  an extremely common existing handle. Vary the style across suggestions (some short/punchy, some
  descriptive, some wordplay).
- bio_suggestion: a single sample bio line (max 150 characters) fitting typical social media bio
  conventions for this niche and tone.

Return ONLY the JSON object, no other text, no markdown formatting."""


def _parse_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_account_suggestions(profile: dict) -> dict:
    prompt = _build_prompt(profile)

    if os.getenv("QWEN_API_KEY"):
        qwen = _get_qwen_client()
        response = qwen.chat.completions.create(
            model="qwen-max",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
        )
        raw = response.choices[0].message.content
    else:
        client = _get_claude_client()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text

    return _parse_response(raw)
