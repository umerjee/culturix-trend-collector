"""AI-drafts a directional relationship dynamic between two existing
Characters — "Generate relationship" in RelationshipManager.tsx. Same
Qwen-max primary / Claude Haiku fallback pattern as
culturetoon_script.py, reused rather than shared directly since this is a
single-shot structured draft, not the shot-list/retry shape script
generation needs.

Returns a draft dict only — never writes to the database. The caller
(app/routers/culturetoons.py) is responsible for persisting it (or not),
so the user can edit before saving and an existing relationship's data is
never silently overwritten."""
import json
import logging
import os

logger = logging.getLogger("culturix.services.culturetoon_relationship")

# Mirrors _RELATIONSHIP_TYPES' keys in app/routers/culturetoons.py — kept
# duplicated rather than imported, same reasoning as culturetoon_script.py's
# own EXPRESSION_NAMES duplication (a service importing from a router runs
# the dependency direction backwards).
RELATIONSHIP_TYPE_KEYS = [
    "friends", "best_friends", "friendly_rivalry", "rivals", "coworkers",
    "boss_employee", "husband_wife", "parent_child", "siblings", "neighbors",
    "acquaintances", "mentor_student", "enemies", "custom",
]


class RelationshipGenerationError(Exception):
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


def _character_context(c) -> str:
    """c: a Character ORM object. personality is {"traits": {...},
    "behavioral_rules": [...], "speech_rules": [...]} — see Character's
    docstring. culture_tags: distinct culture_tag strings across this
    character's own variants, passed in separately since that requires a
    join the caller already has to do once for both characters."""
    bits = [f"Name: {c.name}"]
    if c.description:
        bits.append(f"Description: {c.description}")
    personality = c.personality or {}
    traits = personality.get("traits") or {}
    if traits:
        top = sorted(traits.items(), key=lambda kv: kv[1], reverse=True)[:5]
        bits.append("Personality traits: " + ", ".join(f"{name} ({value:.1f})" for name, value in top))
    if personality.get("behavioral_rules"):
        bits.append("Behavioral DNA: " + "; ".join(personality["behavioral_rules"]))
    if personality.get("speech_rules"):
        bits.append("Speech style: " + "; ".join(personality["speech_rules"]))
    return "\n".join(bits)


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
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        return _parse(raw)
    except json.JSONDecodeError as exc:
        raise RelationshipGenerationError(f"Model returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise RelationshipGenerationError(str(exc)) from exc


def _clamp_level(value, default=5) -> int:
    try:
        return max(0, min(10, int(value)))
    except (TypeError, ValueError):
        return default


def _normalize_direction(raw: dict) -> dict:
    raw = raw or {}
    rules = raw.get("behavior_rules") or []
    if not isinstance(rules, list):
        rules = [str(rules)]
    return {
        "affection_level": _clamp_level(raw.get("affection_level")),
        "trust_level": _clamp_level(raw.get("trust_level")),
        "conflict_level": _clamp_level(raw.get("conflict_level")),
        "perspective_description": (raw.get("perspective_description") or "").strip() or None,
        "behavior_rules": [str(r).strip() for r in rules if str(r).strip()],
    }


def generate_relationship_dynamic(character_a, character_b, culture_a: str = "", culture_b: str = "") -> dict:
    """character_a/character_b: Character ORM objects. culture_a/culture_b:
    optional free text summarizing that character's cultural context
    (caller resolves from CharacterVariant.culture_tag — see
    app/routers/culturetoons.py::generate_relationship). Returns a draft
    dict: relationship_type, relationship_type_label, description,
    comedy_chemistry, a_to_b, b_to_a — never persisted here."""
    name_a, name_b = character_a.name, character_b.name
    context_a = _character_context(character_a) + (f"\nCultural context: {culture_a}" if culture_a else "")
    context_b = _character_context(character_b) + (f"\nCultural context: {culture_b}" if culture_b else "")

    prompt = f"""You are designing a persistent relationship dynamic between two recurring comedy
characters for a series of short character-based videos. Base your answer on who these
characters actually are — their personalities, behavioral DNA, speech style, and cultural
context — not a generic template.

Character A — {name_a}:
{context_a}

Character B — {name_b}:
{context_b}

Design a believable, comedically rich relationship between them. Personality toward another
character is not necessarily symmetrical — {name_a}'s feelings about {name_b} can differ from
{name_b}'s feelings about {name_a} (different affection, trust, conflict, and behavior).

Pick relationship_type from EXACTLY one of: {RELATIONSHIP_TYPE_KEYS}. Use "custom" only if none
of the others genuinely fit, and in that case relationship_type_label should be your own short
label for it; otherwise relationship_type_label should be a natural human-readable version of
the type you picked (e.g. "friendly_rivalry" -> "Friendly Rivalry").

Return ONLY valid JSON with exactly these keys:
- relationship_type: string, one of the allowed values above
- relationship_type_label: string
- description: string, a general/neutral 1-2 sentence description of the pair's dynamic
- comedy_chemistry: integer 0-10, how naturally this pair generates funny interactions
- a_to_b: object with affection_level (0-10 int), trust_level (0-10 int), conflict_level (0-10 int),
  perspective_description (string, {name_a}'s own view of {name_b}, 1 sentence),
  behavior_rules (array of 2-4 short strings describing how {name_a} specifically behaves toward {name_b})
- b_to_a: same shape as a_to_b, but {name_b}'s view of and behavior toward {name_a}

Return ONLY the JSON object, no other text."""

    parsed = _call_llm(prompt)

    relationship_type = parsed.get("relationship_type")
    if relationship_type not in RELATIONSHIP_TYPE_KEYS:
        relationship_type = "custom"
    relationship_type_label = (parsed.get("relationship_type_label") or "").strip() or relationship_type.replace("_", " ").title()

    return {
        "relationship_type": relationship_type,
        "relationship_type_label": relationship_type_label,
        "description": (parsed.get("description") or "").strip() or None,
        "comedy_chemistry": _clamp_level(parsed.get("comedy_chemistry")),
        "a_to_b": _normalize_direction(parsed.get("a_to_b")),
        "b_to_a": _normalize_direction(parsed.get("b_to_a")),
    }
