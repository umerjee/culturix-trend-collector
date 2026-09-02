"""Generates the environment — setting, per-shot lighting and blocking — for a
script that is already written.

Deliberately separate from culturetoon_script's generation and revision: this
never touches the writing. It takes a finished script and describes only how
it LOOKS, so it can be run against approved scripts without putting their
comedy or their approval at risk.

Two callers share it, which is why it lives here rather than in either one:
  * scripts/backfill_script_environment.py, filling scripts written before
    these fields existed (overwrite=False — only fills what is empty)
  * the POST /scripts/{id}/environment endpoint behind the Environment box's
    AI control (overwrite=True — the user explicitly asked for a new one)
"""
import logging
from typing import Optional

from app.services.culturetoon_script import (
    _call_llm_json,
    _format_script_for_prompt,
    label_speakers,
)

logger = logging.getLogger("culturix.services.culturetoon_environment")


class EnvironmentGenerationError(Exception):
    pass


def needs_environment(script) -> bool:
    """True when anything is missing — no setting, or any shot without
    lighting or blocking."""
    if not (getattr(script, "scene_direction", None) or "").strip():
        return True
    return any(
        not (shot or {}).get("lighting") or not (shot or {}).get("blocking")
        for shot in (getattr(script, "shots", None) or [])
    )


def build_environment_prompt(script, variants, note: Optional[str] = None) -> str:
    shots = label_speakers(script.shots or [], variants)
    draft = _format_script_for_prompt(
        {"hook_line": script.hook_line, "shots": shots, "setting": script.scene_direction}
    )
    cast = ", ".join(f"{v.name} ({v.description or 'no description'})" for v in variants) or "unknown"
    numbers = [s.get("shot_number") for s in shots]
    # The user's own idea outranks everything else — it is the whole reason
    # they opened the box — so it goes last, where it is read as the final
    # instruction rather than as background context.
    note_line = (
        f"\n\nTHE USER ASKED SPECIFICALLY FOR THIS, AND IT OVERRIDES THE GUIDANCE ABOVE "
        f"WHERE THEY CONFLICT: \"{note.strip()}\"\n"
        if (note or "").strip() else ""
    )

    return f"""You are a cinematographer adding visual direction to a comedy script that is
ALREADY WRITTEN and already approved. Do NOT rewrite it. Do not change the jokes, the
dialogue, the story, or what anyone does. You are only describing how it LOOKS.

CAST: {cast}

THE SCRIPT:
{draft}

Return JSON with exactly these keys:

- "setting": the physical world this scene happens in, described as a PLACE, in ~25 words.
  Put the scene INSIDE whatever it is about, don't put it in a room where people discuss
  that thing. If the script is about Minecraft, the setting is "Inside a Minecraft world:
  blocky cubic terrain, pixelated dirt and stone textures, torch-lit cave mouth, pixel-art
  sky" — NOT "a living room where they talk about Minecraft". Describe the empty set: no
  characters in it.
- "shots": one object per shot, each with:
    - "shot_number": {numbers}
    - "lighting": the light in THIS shot with a stated DIRECTION, source and colour
      (max ~15 words), e.g. "orange torchlight from frame left, cold blue skylight from
      the cave mouth right". Keep the direction consistent between shots so they read as
      one continuous scene rather than unrelated clips.
    - "blocking": WHERE each named character sits in the frame and what they physically
      hold (max ~20 words), e.g. "Zara centre holding a pickaxe, Blix frame right with a
      clipboard". Use the real names from the cast above, and keep each character's
      position consistent with the shot's existing visual description.

Every shot must appear. Output JSON only.{note_line}"""


def generate_environment(script, variants, note: Optional[str] = None) -> dict:
    """Returns {"setting": str, "shots": [{shot_number, lighting, blocking}]}."""
    try:
        return _call_llm_json(
            build_environment_prompt(script, variants, note), temperature=0.6, max_tokens=1100
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as one error type
        raise EnvironmentGenerationError(str(exc)) from exc


def apply_environment(script, result: dict, overwrite: bool = False) -> list:
    """Merges a generated environment onto the script in place.

    With overwrite=False only empty fields are filled, so a backfill can be
    re-run and can never clobber something hand-written. With overwrite=True
    the generated values win — the user asked for a new environment.

    Returns a list of human-readable change labels (empty when nothing
    changed). Does not commit.
    """
    setting = (result.get("setting") or "").strip()
    by_number = {
        s.get("shot_number"): s for s in (result.get("shots") or []) if isinstance(s, dict)
    }

    changes = []
    if setting and (overwrite or not (script.scene_direction or "").strip()):
        script.scene_direction = setting
        changes.append("setting")

    # Rebuilt as a new list: SQLAlchemy does not detect in-place mutation of a
    # JSON column, so editing the dicts alone would commit nothing.
    new_shots = []
    lit = blocked = 0
    for shot in script.shots or []:
        shot = dict(shot or {})
        incoming = by_number.get(shot.get("shot_number")) or {}
        for field, counter in (("lighting", "lit"), ("blocking", "blocked")):
            value = (incoming.get(field) or "").strip()
            if value and (overwrite or not (shot.get(field) or "").strip()):
                shot[field] = value
                if counter == "lit":
                    lit += 1
                else:
                    blocked += 1
        new_shots.append(shot)

    if lit or blocked:
        script.shots = new_shots
        changes.append(f"lighting×{lit}")
        changes.append(f"blocking×{blocked}")
    return changes
