"""AI-drafts a Character's personality (traits/behavioral_rules/speech_rules)
from its existing description plus an optional free-text hint — "Generate
personality" in CharacterVariantManager.tsx. Same Qwen-max primary / Claude
Haiku fallback pattern as culturetoon_script.py and culturetoon_relationship.py.

Returns a draft dict only — never writes to the database. The caller
(app/routers/culturetoons.py) returns it to the frontend, which pre-fills the
existing trait sliders / rule lists for the user to review and tweak before
saving via the existing PUT /characters/{id}, exactly the pattern
generate_relationship_dynamic() already established for relationships."""
import json
import logging
import os

logger = logging.getLogger("culturix.services.culturetoon_personality")

# Mirrors PERSONALITY_TRAITS in culturix-web/src/lib/types.ts — kept
# duplicated rather than imported, same reasoning as culturetoon_script.py's
# own EXPRESSION_NAMES duplication (a service importing frontend constants
# isn't possible at all, and importing from a router would run the backend
# dependency direction backwards).
PERSONALITY_TRAIT_KEYS = [
    "confidence", "humor", "patience", "competitiveness",
    "warmth", "risk_tolerance", "formality", "impulsiveness",
]


class PersonalityGenerationError(Exception):
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


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _call_llm(prompt: str) -> dict:
    try:
        if os.getenv("QWEN_API_KEY"):
            qwen = _get_qwen_client()
            response = qwen.chat.completions.create(
                model="qwen-max",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
            )
            raw = response.choices[0].message.content
        else:
            client = _get_claude_client()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        return _parse(raw)
    except json.JSONDecodeError as exc:
        raise PersonalityGenerationError(f"Model returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise PersonalityGenerationError(str(exc)) from exc


def _clamp01(value, default=0.5) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 2)
    except (TypeError, ValueError):
        return default


def generate_character_personality(character, hint: str = "") -> dict:
    """character: a Character ORM object (name/description/art_style read).
    hint: optional free-text steering from the user (e.g. "sarcastic older
    brother who loves cricket") — character.description alone is often thin
    (a visual/casting description, not a personality brief), so hint is the
    main lever for getting a personality that isn't generic.

    Returns {"traits": {trait_key: 0-1 float, ...}, "behavioral_rules":
    [str, ...], "speech_rules": [str, ...]} — the exact shape
    _validate_personality() in app/routers/culturetoons.py expects, so the
    frontend can pre-fill the sliders/lists directly."""
    name = character.name
    description = (character.description or "").strip() or "no description set"
    hint = (hint or "").strip()

    prompt = f"""You are designing a recurring comedy character's personality for a series
of short character-based videos.

Character name: {name}
Description: {description}
Art style: {getattr(character, 'art_style', None) or 'n/a'}
{f"Additional guidance from the creator: {hint}" if hint else ""}

Give this character a specific, comedically useful personality — avoid generic/bland
traits. Base it on who this character actually is, not a template.

Return ONLY valid JSON with exactly these keys:
- traits: object with EXACTLY these keys, each a number from 0.0 to 1.0: {PERSONALITY_TRAIT_KEYS}
- behavioral_rules: array of 2-4 short strings describing how {name} consistently behaves
  (e.g. "always one-ups other people's stories")
- speech_rules: array of 2-4 short strings describing how {name} talks
  (e.g. "peppers sentences with dad jokes", "speaks in short clipped sentences")

Return ONLY the JSON object, no other text."""

    parsed = _call_llm(prompt)

    raw_traits = parsed.get("traits") or {}
    traits = {key: _clamp01(raw_traits.get(key, 0.5)) for key in PERSONALITY_TRAIT_KEYS}

    def _rules(key):
        value = parsed.get(key) or []
        if not isinstance(value, list):
            value = [str(value)]
        return [str(r).strip() for r in value if str(r).strip()]

    return {
        "traits": traits,
        "behavioral_rules": _rules("behavioral_rules"),
        "speech_rules": _rules("speech_rules"),
    }
