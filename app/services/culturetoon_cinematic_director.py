"""AI shot-list planning for a ToonScene — the "CinematicDirector" role
from docs/culturix-cinematic-shots.md, Section 5. Implemented as a plain
Python function, NOT a LangGraph node: LangGraph in this codebase is used
exclusively by the separate trend-collection pipeline
(app/pipeline/graph.py) — CultureToons' entire generation stack (scripts,
scenes, relationships) is plain FastAPI-route-driven Python. Introducing
LangGraph for one planning function would be a larger, riskier
architectural change than the shot upgrade itself, for no functional
benefit here; this module fulfills the same responsibility (decide cuts,
shot type, framing, movement, action, emotion, dialogue placement,
reaction shots, reveals, comedic timing) as an ordinary service function,
consistent with culturetoon_script.py's existing pattern.

Deliberately decides when NOT to make a shot a talking-head shot — the
whole point of this existing is that today's one-call-per-scene prototype
defaults to "characters stand and talk," per the spec's own framing."""
import json
import logging
import os

from app.models.toon_shot import SHOT_TYPES, CAMERA_MOVEMENTS, COMEDIC_BEATS, MIN_SHOT_DURATION_SECONDS, MAX_SHOT_DURATION_SECONDS

logger = logging.getLogger("culturix.services.culturetoon_cinematic_director")

EXPRESSION_NAMES = [
    "Angry", "Confused", "Happy", "Shocked", "Laughing",
    "Side-eye", "Crying", "Annoyed", "Smiling", "Deadpan",
]

MIN_SHOTS = 3
MAX_SHOTS = 10
MIN_TOTAL_SECONDS = 8
MAX_TOTAL_SECONDS = 30


class CinematicDirectorError(Exception):
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
                temperature=0.85,
            )
            raw = response.choices[0].message.content
        else:
            client = _get_claude_client()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1800,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        return _parse(raw)
    except json.JSONDecodeError as exc:
        raise CinematicDirectorError(f"Model returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise CinematicDirectorError(str(exc)) from exc


def _clamp_duration(value) -> int:
    try:
        return max(MIN_SHOT_DURATION_SECONDS, min(MAX_SHOT_DURATION_SECONDS, int(value)))
    except (TypeError, ValueError):
        return 3


def plan_shots(
    scene_summary: str,
    cast: list,
    relationship_context: str = "",
    location_description: str = "",
    tone: str = "funny",
    target_duration_seconds: int = 20,
) -> list:
    """cast: list of {"variant_id": str, "name": str, "description": str}
    for every character available to this scene. Returns a list of shot
    draft dicts (shot_number, shot_type, duration_seconds, character_names
    [resolved to variant_ids by the caller — this function only sees
    names], action, emotion, dialogue, comedic_beat, camera_framing,
    camera_angle, camera_movement, lens, composition, lighting) — never
    persisted here, same "AI drafts, caller persists" pattern as
    culturetoon_relationship.py::generate_relationship_dynamic."""
    if not cast:
        raise CinematicDirectorError("Cannot plan shots for a scene with no cast")

    cast_block = "\n".join(f"- {c['name']}: {c.get('description') or 'no further description'}" for c in cast)
    target_duration_seconds = max(MIN_TOTAL_SECONDS, min(MAX_TOTAL_SECONDS, target_duration_seconds))

    prompt = f"""You are a comedy director planning the shot list for one scene of a short vertical
character-based comedy video. Break this scene into a sequence of individual camera shots —
do NOT default to a single talking-head shot of characters standing and talking. Deliberately
vary shot type and use silent/reaction/visual beats, not just dialogue.

Scene: {scene_summary}
Tone: {tone}
Location: {location_description or "not specified — assume a plain neutral setting"}
Cast available:
{cast_block}
{f"Relationship context: {relationship_context}" if relationship_context else ""}

Plan a sequence of {MIN_SHOTS}-{MAX_SHOTS} shots totaling approximately {target_duration_seconds} seconds
(hard limits: {MIN_TOTAL_SECONDS}-{MAX_TOTAL_SECONDS}s total, each shot {MIN_SHOT_DURATION_SECONDS}-{MAX_SHOT_DURATION_SECONDS}s).
Vary shot_type meaningfully across the sequence — use establishing/entrance-style wide shots to
open, reaction and close-up shots for comedic beats, two-shots or over-the-shoulder for
dialogue exchanges, and a clear visual or comedic punchline shot near the end. Not every shot
needs dialogue — silent reaction/visual beats are often funnier.

shot_type must be one of: {SHOT_TYPES}
camera_movement must be one of (or null): {CAMERA_MOVEMENTS}
comedic_beat must be one of (or null): {COMEDIC_BEATS}
emotion must be one of (or null): {EXPRESSION_NAMES}

Return ONLY valid JSON: a list of shot objects, each with exactly these keys:
- shot_number (int, 1..N, no gaps)
- shot_type (string, from the allowed list)
- duration_seconds (int)
- character_names (array of strings, must exactly match names from the cast list above — empty
  array for a pure environmental/insert shot with no character in frame)
- action (string, what happens visually in this shot)
- emotion (string or null)
- dialogue (string or null)
- comedic_beat (string or null, from the allowed list)
- camera_framing (short string, e.g. "character positioned left third, negative space right")
- camera_angle (short string, e.g. "eye level", "low angle")
- camera_movement (string or null, from the allowed list)
- lens (short string, e.g. "35mm wide")
- composition (short string)
- lighting (short string)

Return ONLY the JSON array, no other text."""

    parsed = _call_llm(prompt)
    shots = parsed if isinstance(parsed, list) else parsed.get("shots") or []
    if not shots:
        raise CinematicDirectorError("Model returned no shots")

    cast_by_name = {c["name"].strip().lower(): c["variant_id"] for c in cast}
    result = []
    for i, shot in enumerate(shots, start=1):
        names = shot.get("character_names") or []
        variant_ids = [cast_by_name[n.strip().lower()] for n in names if n.strip().lower() in cast_by_name]
        shot_type = shot.get("shot_type") if shot.get("shot_type") in SHOT_TYPES else "medium"
        comedic_beat = shot.get("comedic_beat") if shot.get("comedic_beat") in COMEDIC_BEATS else None
        camera_movement = shot.get("camera_movement") if shot.get("camera_movement") in CAMERA_MOVEMENTS else None
        emotion = shot.get("emotion") if shot.get("emotion") in EXPRESSION_NAMES else None
        result.append({
            "shot_number": i,
            "shot_type": shot_type,
            "duration_seconds": _clamp_duration(shot.get("duration_seconds")),
            "character_variant_ids": variant_ids,
            "action": (shot.get("action") or "").strip() or None,
            "emotion": emotion,
            "dialogue": (shot.get("dialogue") or "").strip() or None,
            "comedic_beat": comedic_beat,
            "camera_framing": (shot.get("camera_framing") or "").strip() or None,
            "camera_angle": (shot.get("camera_angle") or "").strip() or None,
            "camera_movement": camera_movement,
            "lens": (shot.get("lens") or "").strip() or None,
            "composition": (shot.get("composition") or "").strip() or None,
            "lighting": (shot.get("lighting") or "").strip() or None,
        })
    return result
