"""AI-drafts a whole cast — multiple Characters plus the relationships
between them — from one free-text description of a show/concept. "Describe
your show" in CastPlanWizard.tsx, the batch alternative to describing one
character at a time (see culturetoon_personality.py/culturetoon_relationship.py
for the one-at-a-time generators this reuses the validation helpers from).

A cast is generated together, not character-by-character, so the ensemble
reads as coherent (who's the mom, who's the rival, how they all know each
other) rather than independently-invented people bolted together after the
fact.

Returns a draft dict only — never writes to the database. The caller
(app/routers/culturetoons.py) returns it to the frontend, which lets the
user edit/exclude characters and relationships before creating anything —
same never-silently-persist contract as the other two generators."""
import json
import logging
import os

from app.services.culturetoon_personality import PERSONALITY_TRAIT_KEYS
from app.services.culturetoon_relationship import RELATIONSHIP_TYPE_KEYS, _clamp_level, _normalize_direction

logger = logging.getLogger("culturix.services.culturetoon_cast")

MIN_CAST_SIZE = 2
MAX_CAST_SIZE = 6


class CastGenerationError(Exception):
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
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        return _parse(raw)
    except json.JSONDecodeError as exc:
        raise CastGenerationError(f"Model returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise CastGenerationError(str(exc)) from exc


def _clamp01(value, default=0.5) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 2)
    except (TypeError, ValueError):
        return default


def _normalize_personality(raw: dict) -> dict:
    raw = raw or {}
    raw_traits = raw.get("traits") or {}
    traits = {key: _clamp01(raw_traits.get(key, 0.5)) for key in PERSONALITY_TRAIT_KEYS}

    def _rules(key):
        value = raw.get(key) or []
        if not isinstance(value, list):
            value = [str(value)]
        return [str(r).strip() for r in value if str(r).strip()]

    return {"traits": traits, "behavioral_rules": _rules("behavioral_rules"), "speech_rules": _rules("speech_rules")}


def generate_cast_plan(plan_description: str, existing_character_names: list = None) -> dict:
    """plan_description: free text describing the show/account (setting,
    vibe, who's in it). existing_character_names: optional list of names
    already in the brand's cast, passed as light context only — this call
    never generates relationships crossing into the existing cast, just
    context so the new batch doesn't invent an obvious duplicate.

    Returns {"characters": [{"name", "description", "suggested_main",
    "personality"}, ...], "relationships": [{"character_a_index",
    "character_b_index", "relationship_type", "relationship_type_label",
    "description", "comedy_chemistry", "a_to_b", "b_to_a"}, ...]} — indices
    refer into the "characters" list above, since names aren't stable keys
    until the characters are actually created."""
    plan_description = (plan_description or "").strip()
    if not plan_description:
        raise CastGenerationError("plan_description is required")
    existing_line = (
        f"\nThis brand already has these characters (do not recreate them, but you may reference "
        f"them for context): {', '.join(existing_character_names)}\n"
        if existing_character_names else ""
    )

    prompt = f"""You are casting a roster of recurring comedy characters for a series of short
character-based videos, from the creator's own description of their show.

Show description: {plan_description}
{existing_line}
Design a cast of {MIN_CAST_SIZE}-{MAX_CAST_SIZE} distinct, comedically useful characters who
genuinely fit this description — not generic template characters. Then design the relationship
between every pair of characters who would plausibly interact (not necessarily every possible
pair — skip pairs with no real connection). Exactly one character should be marked
suggested_main: true — the one the show is centered on.

Return ONLY valid JSON with exactly these keys:
- characters: array of {MIN_CAST_SIZE}-{MAX_CAST_SIZE} objects, each with exactly:
  - name: string
  - description: string, 1-2 sentences (appearance/role/personality summary)
  - suggested_main: boolean (true for exactly one character)
  - personality: object with:
    - traits: object with EXACTLY these keys, each 0.0-1.0: {PERSONALITY_TRAIT_KEYS}
    - behavioral_rules: array of 2-4 short strings
    - speech_rules: array of 2-4 short strings
- relationships: array of objects, each with exactly:
  - character_a_index: integer (0-based index into the characters array above)
  - character_b_index: integer (different from character_a_index)
  - relationship_type: string, one of EXACTLY: {RELATIONSHIP_TYPE_KEYS}
  - relationship_type_label: string (human-readable; only meaningfully different from
    relationship_type when relationship_type is "custom")
  - description: string, 1-2 sentences, general/neutral
  - comedy_chemistry: integer 0-10
  - a_to_b: object with affection_level (0-10 int), trust_level (0-10 int), conflict_level (0-10 int),
    perspective_description (string, character_a's view of character_b), behavior_rules (array of 2-4 strings)
  - b_to_a: same shape as a_to_b, but character_b's view of and behavior toward character_a

Return ONLY the JSON object, no other text."""

    parsed = _call_llm(prompt)

    raw_characters = parsed.get("characters") or []
    if not isinstance(raw_characters, list) or not raw_characters:
        raise CastGenerationError("Model returned no characters")
    raw_characters = raw_characters[:MAX_CAST_SIZE]
    num_characters = len(raw_characters)

    characters = []
    main_assigned = False
    for c in raw_characters:
        c = c or {}
        is_main = bool(c.get("suggested_main")) and not main_assigned
        if is_main:
            main_assigned = True
        characters.append({
            "name": (c.get("name") or "").strip() or "Unnamed Character",
            "description": (c.get("description") or "").strip(),
            "suggested_main": is_main,
            "personality": _normalize_personality(c.get("personality")),
        })
    if not main_assigned:
        characters[0]["suggested_main"] = True

    relationships = []
    for r in parsed.get("relationships") or []:
        r = r or {}
        try:
            a_index, b_index = int(r.get("character_a_index")), int(r.get("character_b_index"))
        except (TypeError, ValueError):
            continue
        if a_index == b_index or not (0 <= a_index < num_characters) or not (0 <= b_index < num_characters):
            continue
        relationship_type = r.get("relationship_type")
        if relationship_type not in RELATIONSHIP_TYPE_KEYS:
            relationship_type = "custom"
        relationship_type_label = (r.get("relationship_type_label") or "").strip() or relationship_type.replace("_", " ").title()
        relationships.append({
            "character_a_index": a_index,
            "character_b_index": b_index,
            "relationship_type": relationship_type,
            "relationship_type_label": relationship_type_label,
            "description": (r.get("description") or "").strip() or None,
            "comedy_chemistry": _clamp_level(r.get("comedy_chemistry")),
            "a_to_b": _normalize_direction(r.get("a_to_b")),
            "b_to_a": _normalize_direction(r.get("b_to_a")),
        })

    return {"characters": characters, "relationships": relationships}
