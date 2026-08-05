"""Trend-tied script generation for CultureToons — combines
clip_script.py's Persona/Cluster context-branching with
shopify/content_ideas.py's structured-JSON-output pattern (three distinct
fields are needed here — hook/dialogue/scene direction — not one plain-text
voiceover blob). Same Qwen-max primary / Claude Haiku fallback provider
pattern as every other content generator in this codebase.
"""
import json
import logging
import os
from typing import Optional

from app.models.persona import Persona

logger = logging.getLogger("culturix.services.culturetoon_script")


class ToonScriptGenerationError(Exception):
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
            f"Interests: {p.interests or 'n/a'}"
        )
    c = persona_or_cluster
    return "cluster", (
        f"Trend theme: {c.theme or 'n/a'}\n"
        f"Summary: {c.summary or 'n/a'}"
    )


def _build_prompt(persona_or_cluster, variant=None) -> str:
    source_type, context = _source_type_and_context(persona_or_cluster)
    variant_line = ""
    if variant is not None:
        variant_line = (
            f"\nWrite this specifically for the character '{variant.name}' "
            f"({variant.description or variant.culture_tag or 'no further description'}). "
            f"The dialogue must be voiced as this character reacting to the trend below, "
            f"in a way that reflects their cultural humor/perspective.\n"
        )

    return f"""You are a scriptwriter for short (10-15 second) character-based comedy
skits for social video, grounded in the {source_type} below.

{context}
{variant_line}
Format example (for tone/shape only, don't reuse the content):
Hook: "Indian moms when you say you're not hungry."
Dialogue: Mom: "Okay… I'll make something small."
Scene direction: Cut to: 12 dishes.

Requirements:
- Short, punchy, visual — this is a 10-15 second skit, not a monologue.
- The hook must work as a stand-alone opening line/on-screen text.
- The dialogue is what the character actually says out loud.
- The scene direction is the punchline visual beat (a "cut to" or similar).

Return ONLY valid JSON with exactly these keys:
- hook_line: the punchy opening line (max 15 words)
- dialogue: the spoken line(s), attributed to the character (e.g. `Mom: "..."`)
- scene_direction: a short stage/scene direction for the punchline beat (max 15 words)

Return ONLY the JSON object, no other text."""


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_toon_script(persona_or_cluster, variant: Optional[object] = None) -> dict:
    """Returns {"hook_line": str, "dialogue": str, "scene_direction": str}."""
    prompt = _build_prompt(persona_or_cluster, variant)
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
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        return _parse(raw)
    except json.JSONDecodeError as exc:
        raise ToonScriptGenerationError(f"Model returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise ToonScriptGenerationError(str(exc)) from exc
