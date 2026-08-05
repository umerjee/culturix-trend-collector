"""Trend-tied script generation for CultureToons — combines
clip_script.py's Persona/Cluster context-branching with
shopify/content_ideas.py's structured-JSON-output pattern. Same Qwen-max
primary / Claude Haiku fallback provider pattern as every other content
generator in this codebase.

Scripts are shot-structured (a list of {shot_number, duration_seconds,
action, expression, dialogue}), not a single flat hook/dialogue/scene blob —
this is what lets build_kling_prompt() assemble Kling Omni's multi-shot DSL
("shot n,m,words; shot n,m,words;") directly from a stored script, once a
CharacterVariant has been registered as a Kling Element (see
app/media/kling_omni.py / app/services/culturetoon_element.py).
"""
import json
import logging
import os
from typing import Optional

from app.models.persona import Persona

logger = logging.getLogger("culturix.services.culturetoon_script")

# Duplicated from app/routers/culturetoons.py's EXPRESSION_NAMES rather than
# imported — a service importing from a router would run the dependency
# direction backwards, and this codebase already has precedent for small
# duplicated constants/helpers over that kind of coupling (e.g.
# clips.py::_fetch_source / culturetoons.py::_fetch_trend_source).
EXPRESSION_NAMES = [
    "Angry", "Confused", "Happy", "Shocked", "Laughing",
    "Side-eye", "Crying", "Annoyed", "Smiling", "Deadpan",
]

TONE_OPTIONS = ["funny", "dramatic", "satiric", "sad", "wholesome", "chaotic", "deadpan"]

# Public (no leading underscore) — app/routers/culturetoons.py validates
# user-supplied num_shots/target_duration_seconds against these before
# calling the LLM, so an out-of-range request 400s immediately instead of
# failing later inside build_kling_prompt after already spending a call.
MIN_SHOTS = 2
MAX_SHOTS = 6
MIN_TOTAL_SECONDS = 3
MAX_TOTAL_SECONDS = 15
_MAX_SHOT_PROMPT_CHARS = 512


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


def _variant_line(variant, source_type: str) -> str:
    if variant is None:
        return ""
    return (
        f"\nWrite this specifically for the character '{variant.name}' "
        f"({variant.description or variant.culture_tag or 'no further description'}). "
        f"Every shot's action/dialogue must be something THIS character does/says, "
        f"reacting to the {source_type} below in a way that reflects their cultural humor/perspective.\n"
    )


def _build_prompt_from_context(source_type: str, context: str, variant, tone: str,
                                num_shots: int, target_duration_seconds: int) -> str:
    variant_line = _variant_line(variant, source_type)

    return f"""You are a scriptwriter for short character-based comedy skits for
social video, grounded in the {source_type} below. The tone must be: {tone}.

{context}
{variant_line}
Aim for around {num_shots} shots totaling about {target_duration_seconds} seconds, though you
may adjust within the hard limits below if it better serves the joke.

Requirements:
- Between {MIN_SHOTS} and {MAX_SHOTS} shots. shot_number must be 1, 2, 3... with no gaps.
- Each shot's duration_seconds is a whole number >= 1. The SUM of all shots'
  duration_seconds must be between {MIN_TOTAL_SECONDS} and {MAX_TOTAL_SECONDS} (hard limits).
- "action" describes what the character visually does in that shot (max ~20 words).
- "expression" is one of exactly these values, or null if not relevant: {EXPRESSION_NAMES}.
- "dialogue" is what the character says out loud in that shot, or null for a
  silent/reaction-only beat.
- hook_line is a punchy, stand-alone opening line/on-screen text summarizing the skit (max 15 words).

Return ONLY valid JSON with exactly these keys:
- hook_line: string
- shots: array of objects, each with exactly: shot_number (int), duration_seconds (int),
  action (string), expression (string or null), dialogue (string or null)

Return ONLY the JSON object, no other text."""


def _build_prompt(persona_or_cluster, variant, tone: str, num_shots: int, target_duration_seconds: int) -> str:
    source_type, context = _source_type_and_context(persona_or_cluster)
    return _build_prompt_from_context(source_type, context, variant, tone, num_shots, target_duration_seconds)


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _call_llm_for_script(prompt: str, tone: str) -> dict:
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
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        parsed = _parse(raw)
    except json.JSONDecodeError as exc:
        raise ToonScriptGenerationError(f"Model returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise ToonScriptGenerationError(str(exc)) from exc

    shots = parsed.get("shots") or []
    total = sum(s.get("duration_seconds", 0) for s in shots) if shots else 0
    return {
        "hook_line": parsed.get("hook_line"),
        "tone": tone,
        "shots": shots,
        "total_duration_seconds": parsed.get("total_duration_seconds") or total,
    }


def generate_toon_script(persona_or_cluster, variant: Optional[object] = None, tone: str = "funny",
                          num_shots: int = 4, target_duration_seconds: int = 12) -> dict:
    """Returns {"hook_line": str, "tone": str,
      "shots": [{"shot_number", "duration_seconds", "action", "expression", "dialogue"}, ...],
      "total_duration_seconds": int}."""
    prompt = _build_prompt(persona_or_cluster, variant, tone, num_shots, target_duration_seconds)
    return _call_llm_for_script(prompt, tone)


def generate_toon_script_from_idea(idea: str, variant: Optional[object] = None, tone: str = "funny",
                                    num_shots: int = 4, target_duration_seconds: int = 12) -> dict:
    """Same shape/contract as generate_toon_script, but grounded in the
    user's own free-text scenario idea instead of a live trending Persona
    or Cluster — for when someone already knows what they want the
    character to react to and doesn't want to wait for/browse trends."""
    context = f"User's scenario idea: {idea.strip()}"
    prompt = _build_prompt_from_context("user-provided scenario idea", context, variant, tone,
                                         num_shots, target_duration_seconds)
    return _call_llm_for_script(prompt, tone)


def build_kling_prompt(shots: list, element_name: str) -> str:
    """Assembles Kling Omni's multi-shot DSL string ("shot n, m, words; ...")
    from stored shots + a registered element_name. Raises
    ToonScriptGenerationError on any structural problem — empty/too-many
    shots, non-contiguous shot_number values, an out-of-bounds total
    duration, or a per-shot built prompt exceeding Kling's 512-char cap.

    @{element_name} is referenced in every shot segment (not just the
    first) — the safer explicit-over-implicit default; cheap to change here
    alone if a live test shows Kling tracks the character across shots
    without repeating the reference."""
    if not shots:
        raise ToonScriptGenerationError("Cannot build a Kling prompt from an empty shots list")
    if len(shots) > MAX_SHOTS:
        raise ToonScriptGenerationError(f"Kling supports at most {MAX_SHOTS} shots, got {len(shots)}")

    expected_numbers = list(range(1, len(shots) + 1))
    actual_numbers = [s.get("shot_number") for s in shots]
    if actual_numbers != expected_numbers:
        raise ToonScriptGenerationError(
            f"shot_number values must be a contiguous 1..N sequence, got {actual_numbers}"
        )

    total_seconds = sum(s.get("duration_seconds", 0) for s in shots)
    if not (MIN_TOTAL_SECONDS <= total_seconds <= MAX_TOTAL_SECONDS):
        raise ToonScriptGenerationError(
            f"Total shot duration must be between {MIN_TOTAL_SECONDS} and {MAX_TOTAL_SECONDS}s, got {total_seconds}s"
        )

    segments = []
    for shot in shots:
        duration = shot.get("duration_seconds")
        if not isinstance(duration, int) or duration < 1:
            raise ToonScriptGenerationError(
                f"Shot {shot.get('shot_number')} has an invalid duration_seconds: {duration}"
            )

        parts = [f"@{element_name}"]
        action = (shot.get("action") or "").strip()
        if action:
            parts.append(action)
        expression = shot.get("expression")
        if expression:
            parts.append(f"{expression.lower()} expression")
        dialogue = shot.get("dialogue")
        if dialogue:
            parts.append(f'saying "{dialogue}"')

        text = ", ".join(parts) + "."
        if len(text) > _MAX_SHOT_PROMPT_CHARS:
            raise ToonScriptGenerationError(
                f"Shot {shot['shot_number']}'s built prompt text exceeds Kling's "
                f"{_MAX_SHOT_PROMPT_CHARS}-char limit ({len(text)} chars)"
            )
        segments.append(f"shot {shot['shot_number']}, {duration}, {text}")

    return "; ".join(segments) + ";"
