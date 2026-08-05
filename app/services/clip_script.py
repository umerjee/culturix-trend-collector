"""Script generation for Phase 7 clip generation — turns a Persona or Cluster
into a punchy, hook-first ~30-45s spoken script (80-110 words), reusing the
same Qwen-max primary / Claude Haiku fallback pattern as content_strategist.py
and shopify/content_ideas.py (this codebase's established content-generation
convention — there is no dedicated "Instagram caption pipeline" module to
reuse, despite what an earlier version of this spec assumed).
"""
import logging
import os

from app.models.persona import Persona

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


def _source_type_and_context(persona_or_cluster) -> tuple[str, str]:
    if isinstance(persona_or_cluster, Persona):
        p = persona_or_cluster
        return "persona", (
            f"Persona name: {p.name}\n"
            f"Description: {p.description}\n"
            f"Motivations: {p.motivations or 'n/a'}\n"
            f"Interests: {p.interests or 'n/a'}\n"
            f"Content angle ideas: {p.content_suggestions or 'n/a'}"
        )
    c = persona_or_cluster
    return "cluster", (
        f"Trend theme: {c.theme or 'n/a'}\n"
        f"Summary: {c.summary or 'n/a'}"
    )


def _build_prompt(persona_or_cluster) -> str:
    source_type, context = _source_type_and_context(persona_or_cluster)
    return f"""You are a short-form video scriptwriter for TikTok/Instagram Reels/YouTube Shorts.

Write a spoken voiceover script grounded in the {source_type} below.

{context}

Requirements:
- Hook-first: the opening line must grab attention in under 2 seconds.
- 80-110 words total, punchy short-form style — spoken, not written prose.
- Roughly 30-45 seconds when read aloud at a natural pace.
- Plain spoken text only — no markdown, no stage directions, no emoji, no hashtags, no surrounding quotation marks.

Return ONLY the script text, nothing else."""


def generate_script(persona_or_cluster) -> str:
    prompt = _build_prompt(persona_or_cluster)
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
