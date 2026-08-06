"""Script generation for faceless-reel media generation ("reel" media_type in
app/media/service.py) — turns a GeneratedContent idea's own hook/caption/cta
(composed client-side into one prompt string by DigestCard.tsx, same
convention every other media type's prompt already follows — see
app/main.py's /api/generate-media) into a punchy, hook-first ~30-45s spoken
script (80-110 words). Reuses the same Qwen-max primary / Claude Haiku
fallback pattern as content_strategist.py and shopify/content_ideas.py.

Originally built for the dormant Phase 7 clips.py pipeline, which generated
a script from scratch off a bare Persona/Cluster row — no page ever let a
user pick one of those directly, so that script could drift from the idea
text the user actually saw and approved on their digest. Grounding on the
idea's own text instead (the same "idea" pattern CultureToons'
generate_toon_script_from_idea already uses successfully) keeps the reel
consistent with what's on screen.
"""
import logging
import os

logger = logging.getLogger("culturix.services.clip_script")


class ScriptGenerationError(Exception):
    pass


def _get_qwen_client():
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["QWEN_API_KEY"],
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )


def _get_claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _build_prompt(idea_text: str) -> str:
    return f"""You are a short-form video scriptwriter for TikTok/Instagram Reels/YouTube Shorts.

Write a spoken voiceover script grounded in the content idea below — a hook, caption, and
call-to-action that a user has already approved for this post. Capture the same core message
and angle, rewritten specifically for something spoken aloud over video.

{idea_text.strip()}

Requirements:
- Hook-first: the opening line must grab attention in under 2 seconds.
- 80-110 words total, punchy short-form style — spoken, not written prose.
- Roughly 30-45 seconds when read aloud at a natural pace.
- Plain spoken text only — no markdown, no stage directions, no emoji, no hashtags, no surrounding quotation marks.

Return ONLY the script text, nothing else."""


def generate_script(idea_text: str) -> str:
    """idea_text: the idea's hook/caption/cta, composed into one string by
    the caller (see DigestCard.tsx's prompts.reel)."""
    if not idea_text or not idea_text.strip():
        raise ScriptGenerationError("Cannot generate a script from empty idea text")
    prompt = _build_prompt(idea_text)
    try:
        if os.getenv("QWEN_API_KEY"):
            qwen = _get_qwen_client()
            response = qwen.chat.completions.create(
                model="qwen-max",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            raw = response.choices[0].message.content
        else:
            client = _get_claude_client()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
    except Exception as exc:
        raise ScriptGenerationError(str(exc)) from exc

    text = (raw or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith(("text", "json")):
            text = text.split("\n", 1)[1] if "\n" in text else ""
    text = text.strip().strip('"').strip()

    if not text:
        raise ScriptGenerationError("Script generation returned empty text")
    return text
