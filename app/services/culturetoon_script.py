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


def _personality_line(v, character_personalities: Optional[dict]) -> str:
    """Renders one variant's parent Character.personality (traits/
    behavioral_rules/speech_rules — see docs/culturix-comedy-architecture.md
    §3.2) as a short inline clause, or "" if no personality is set. Keeping
    character identity deterministic across scripts is the whole point of
    this field existing — without it, the LLM re-improvises personality
    from scratch (or from the vaguer free-text description) every single
    call."""
    if not character_personalities:
        return ""
    personality = character_personalities.get(str(getattr(v, "character_id", "")))
    if not personality:
        return ""
    bits = []
    traits = personality.get("traits") or {}
    if traits:
        top_traits = sorted(traits.items(), key=lambda kv: kv[1], reverse=True)[:4]
        bits.append("traits: " + ", ".join(f"{name} ({value:.1f})" for name, value in top_traits))
    if personality.get("behavioral_rules"):
        bits.append("always: " + "; ".join(personality["behavioral_rules"]))
    if personality.get("speech_rules"):
        bits.append("speech style: " + "; ".join(personality["speech_rules"]))
    return f" [{'; '.join(bits)}]" if bits else ""


def _cast_line(variants: list, source_type: str, character_personalities: Optional[dict] = None) -> str:
    """variants: a list of CharacterVariant-like objects (may be empty).
    Single-character phrasing is kept as its own branch (not just a 1-item
    version of the multi-character one) since it reads more naturally and
    matches this prompt's original, already-tested wording. The
    multi-character branch requires the model to name a REAL character per
    shot via "speaker_name" rather than inventing one — this is the direct
    fix for a script inventing a fictional second character (e.g. a "Marvel
    purist") when only one real variant was ever supplied.

    character_personalities: optional {character_id: personality_dict} —
    see _personality_line. Keyed by Character.id (the base character), not
    CharacterVariant.id, since personality lives on the base Character and
    is shared across its cultural variants."""
    if not variants:
        return ""
    if len(variants) == 1:
        v = variants[0]
        return (
            f"\nWrite this specifically for the character '{v.name}' "
            f"({v.description or v.culture_tag or 'no further description'})"
            f"{_personality_line(v, character_personalities)}. "
            f"Every shot's action/dialogue must be something THIS character does/says, "
            f"reacting to the {source_type} below in a way that reflects their cultural humor/perspective.\n"
        )
    cast_block = "\n".join(
        f"- '{v.name}' ({v.description or v.culture_tag or 'no further description'})"
        f"{_personality_line(v, character_personalities)}"
        for v in variants
    )
    return f"""
This is a scene between these {len(variants)} REAL characters — do not invent any other
character, and every character who appears must be one of these:
{cast_block}
Write actual back-and-forth dialogue/interaction between them, each reacting to the
{source_type} below in a way that reflects their own individual cultural humor/perspective.
Every shot's "speaker_name" must be the exact name of whichever one of these characters is
acting/speaking in that shot.
"""


def _memory_context(memories: Optional[list]) -> str:
    """memories: list of memory content strings, already retrieved/filtered
    by app/services/culturetoon_memory.py::retrieve_relevant_memories for
    relevance to this script's context — see
    docs/culturix-comedy-architecture.md §3.5. Empty string if none."""
    if not memories:
        return ""
    lines = "\n".join(f"- {m}" for m in memories)
    return f"\nRelevant things that happened before, from this character's history (reference naturally if it fits, don't force it):\n{lines}\n"


def _culture_context(cultures: Optional[list]) -> str:
    """cultures: list of serialized Culture dicts (see
    app/models/culture.py — deduped, one per distinct culture actually
    present in the cast, resolved from each variant's culture_id). Surfaces
    real comedy material (common_misunderstandings, positive_traits) AND an
    explicit avoid-list (stereotypes_to_avoid) in the same breath — the
    culture library exists specifically so cultural humor doesn't default
    to demeaning generalizations, per docs/culturix-comedy-architecture.md
    §11/§3.7."""
    if not cultures:
        return ""
    lines = []
    for c in cultures:
        parts = [f"{c['name']}:"]
        if c.get("humor_sensitivity"):
            parts.append(c["humor_sensitivity"])
        if c.get("common_misunderstandings"):
            parts.append("Material to draw on: " + "; ".join(c["common_misunderstandings"]))
        if c.get("positive_traits"):
            parts.append("Positive traits to reflect: " + ", ".join(c["positive_traits"]))
        if c.get("stereotypes_to_avoid"):
            parts.append("AVOID: " + "; ".join(c["stereotypes_to_avoid"]))
        lines.append("- " + " ".join(parts))
    return "\nCultural context (use for authentic material, respect the AVOID guidance strictly):\n" + "\n".join(lines) + "\n"


def _relationship_context(relationships: Optional[list]) -> str:
    """relationships: list of serialized CharacterRelationship dicts (see
    app/routers/culturetoons.py::resolve_relationships_for_cast) — already
    filtered to the pair(s) actually present in this script's cast. Empty
    string if none, so a single-character script or a cast with no stored
    relationship doesn't get a dangling empty section in the prompt."""
    if not relationships:
        return ""
    lines = []
    for r in relationships:
        parts = []
        if r.get("relationship_type"):
            parts.append(r["relationship_type"].replace("_", " "))
        if r.get("description"):
            parts.append(r["description"])
        # affection and trust are independent (e.g. bickering siblings can
        # be low-trust but high-affection) — surface both when set rather
        # than assuming one implies the other.
        dynamics = []
        if r.get("affection_level") is not None:
            dynamics.append(f"affection {r['affection_level']}/10")
        if r.get("trust_level") is not None:
            dynamics.append(f"trust {r['trust_level']}/10")
        if r.get("conflict_level") is not None:
            dynamics.append(f"conflict {r['conflict_level']}/10")
        if dynamics:
            parts.append(", ".join(dynamics))
        if r.get("behavioral_rules"):
            parts.append("Rules: " + "; ".join(r["behavioral_rules"]))
        if parts:
            lines.append("- " + " — ".join(parts))
    if not lines:
        return ""
    return "\nEstablished relationship between these characters (keep the dynamic consistent, don't contradict it):\n" + "\n".join(lines) + "\n"


def _build_prompt_from_context(source_type: str, context: str, variants: list, tone: str,
                                num_shots: int, target_duration_seconds: int,
                                character_personalities: Optional[dict] = None,
                                relationships: Optional[list] = None,
                                memories: Optional[list] = None,
                                cultures: Optional[list] = None,
                                performance_context: Optional[str] = None) -> str:
    cast_line = _cast_line(variants, source_type, character_personalities)
    relationship_line = _relationship_context(relationships)
    memory_line = _memory_context(memories)
    culture_line = _culture_context(cultures)
    performance_line = performance_context or ""
    speaker_field = (
        '\n- "speaker_name" is the exact name of which listed character is acting/speaking in '
        "that shot (required when more than one character is listed; omit or null otherwise)."
        if len(variants) > 1 else ""
    )
    speaker_key = ", speaker_name (string or null)" if len(variants) > 1 else ""

    return f"""You are a scriptwriter for short character-based comedy skits for
social video, grounded in the {source_type} below. The tone must be: {tone}.

{context}
{cast_line}
{relationship_line}
{memory_line}
{culture_line}
{performance_line}
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
- hook_line is a punchy, stand-alone opening line/on-screen text summarizing the skit (max 15 words).{speaker_field}

Return ONLY valid JSON with exactly these keys:
- hook_line: string
- shots: array of objects, each with exactly: shot_number (int), duration_seconds (int),
  action (string), expression (string or null), dialogue (string or null){speaker_key}

Return ONLY the JSON object, no other text."""


def _build_prompt(persona_or_cluster, variants: list, tone: str, num_shots: int, target_duration_seconds: int,
                   character_personalities: Optional[dict] = None, relationships: Optional[list] = None,
                   memories: Optional[list] = None, cultures: Optional[list] = None,
                   performance_context: Optional[str] = None) -> str:
    source_type, context = _source_type_and_context(persona_or_cluster)
    return _build_prompt_from_context(source_type, context, variants, tone, num_shots, target_duration_seconds,
                                       character_personalities, relationships, memories, cultures, performance_context)


def _assign_speakers(shots: list, variants: list) -> list:
    """Maps each shot's LLM-produced "speaker_name" to a real variant's id
    as "speaker_variant_id" (matched case-insensitively against the
    supplied variants; no match or a single-variant script leaves it unset,
    defaulting to the primary/first variant downstream). "speaker_name" is
    dropped from the returned shots — it's an LLM-facing field only, the
    persisted/returned shape uses speaker_variant_id (see ToonScript's
    shots column docstring)."""
    if not variants:
        return shots
    by_name = {v.name.strip().lower(): str(v.id) for v in variants}
    result = []
    for shot in shots:
        shot = dict(shot)
        speaker_name = (shot.pop("speaker_name", None) or "").strip().lower()
        variant_id = by_name.get(speaker_name)
        if variant_id:
            shot["speaker_variant_id"] = variant_id
        result.append(shot)
    return result


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _call_llm_for_script(prompt: str, tone: str, variants: list) -> dict:
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
        "shots": _assign_speakers(shots, variants),
        "total_duration_seconds": parsed.get("total_duration_seconds") or total,
    }


def generate_toon_script(persona_or_cluster, variants: Optional[list] = None, tone: str = "funny",
                          num_shots: int = 4, target_duration_seconds: int = 12,
                          character_personalities: Optional[dict] = None,
                          relationships: Optional[list] = None,
                          memories: Optional[list] = None,
                          cultures: Optional[list] = None,
                          performance_context: Optional[str] = None) -> dict:
    """variants: the full cast for this script (list of CharacterVariant-like
    objects) — one real character writes a monologue, two or more write an
    actual scene between them (see _cast_line). character_personalities:
    optional {character_id: personality_dict}, relationships: optional list
    of serialized CharacterRelationship dicts already filtered to this
    cast — see app/routers/culturetoons.py::resolve_relationships_for_cast.
    Both are how a character's identity stays deterministic across scripts
    instead of being re-improvised by the LLM each call — see
    docs/culturix-comedy-architecture.md §3.2/§3.4. Returns {"hook_line":
    str, "tone": str, "shots": [{"shot_number", "duration_seconds",
    "action", "expression", "dialogue", "speaker_variant_id"}, ...],
    "total_duration_seconds": int}."""
    variants = variants or []
    prompt = _build_prompt(persona_or_cluster, variants, tone, num_shots, target_duration_seconds,
                            character_personalities, relationships, memories, cultures, performance_context)
    return _call_llm_for_script(prompt, tone, variants)


def generate_toon_script_from_idea(idea: str, variants: Optional[list] = None, tone: str = "funny",
                                    num_shots: int = 4, target_duration_seconds: int = 12,
                                    character_personalities: Optional[dict] = None,
                                    relationships: Optional[list] = None,
                                    memories: Optional[list] = None,
                                    cultures: Optional[list] = None,
                                    performance_context: Optional[str] = None) -> dict:
    """Same shape/contract as generate_toon_script, but grounded in the
    user's own free-text scenario idea instead of a live trending Persona
    or Cluster — for when someone already knows what they want the
    character to react to and doesn't want to wait for/browse trends."""
    variants = variants or []
    context = f"User's scenario idea: {idea.strip()}"
    prompt = _build_prompt_from_context("user-provided scenario idea", context, variants, tone,
                                         num_shots, target_duration_seconds,
                                         character_personalities, relationships, memories, cultures,
                                         performance_context)
    return _call_llm_for_script(prompt, tone, variants)


def generate_toon_script_continuing_episode(prior_parts_summary: str, idea: str, variants: Optional[list] = None,
                                             tone: str = "funny", num_shots: int = 4,
                                             target_duration_seconds: int = 12,
                                             character_personalities: Optional[dict] = None,
                                             relationships: Optional[list] = None,
                                             memories: Optional[list] = None,
                                             cultures: Optional[list] = None,
                                             performance_context: Optional[str] = None) -> dict:
    """Same shape/contract as generate_toon_script_from_idea, but grounded in
    a synopsis of an episode's prior parts too (see
    app/routers/culturetoons.py's _episode_synopsis) — the next part is
    written with awareness of what already happened instead of starting
    cold each time, which is what episode stitching otherwise leaves to the
    user to maintain by hand across separately-suggested scripts."""
    variants = variants or []
    context = (
        f"What has happened so far in this story, in order:\n{prior_parts_summary.strip()}\n\n"
        f"What should happen in this NEXT part: {idea.strip()}"
    )
    prompt = _build_prompt_from_context(
        "the ongoing story so far, and what should happen in this next part", context, variants, tone,
        num_shots, target_duration_seconds, character_personalities, relationships, memories, cultures,
        performance_context,
    )
    prompt += (
        "\n\nThis is a continuation, not a new story — do not recap, re-introduce the characters, "
        "or restate what already happened. Continue directly from where the story left off."
    )
    return _call_llm_for_script(prompt, tone, variants)


def build_kling_prompt(shots: list, element_names) -> str:
    """Assembles Kling Omni's multi-shot DSL string ("shot n, m, words; ...")
    from stored shots + registered element name(s). Raises
    ToonScriptGenerationError on any structural problem — empty/too-many
    shots, non-contiguous shot_number values, an out-of-bounds total
    duration, or a per-shot built prompt exceeding Kling's 512-char cap.

    element_names accepts either a single string (single-character script,
    unchanged from before) or a dict of {variant_id: element_name, ...} for
    a multi-character script — each shot's speaker_variant_id (or the dict's
    first entry, as the "primary" speaker, when a shot doesn't set one)
    picks which @ElementName is referenced. @{element_name} is referenced
    in every shot segment (not just the first) — the safer
    explicit-over-implicit default; cheap to change here alone if a live
    test shows Kling tracks characters across shots without repeating the
    reference."""
    if not shots:
        raise ToonScriptGenerationError("Cannot build a Kling prompt from an empty shots list")
    if len(shots) > MAX_SHOTS:
        raise ToonScriptGenerationError(f"Kling supports at most {MAX_SHOTS} shots, got {len(shots)}")

    if isinstance(element_names, str):
        element_map: dict = {}
        default_element = element_names
    else:
        element_map = dict(element_names)
        if not element_map:
            raise ToonScriptGenerationError("build_kling_prompt requires at least one element name")
        default_element = next(iter(element_map.values()))

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

        speaker_variant_id = shot.get("speaker_variant_id")
        element_name = element_map.get(speaker_variant_id, default_element) if element_map else default_element

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
