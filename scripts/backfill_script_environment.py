"""Backfills the environment fields on scripts written before they existed.

`setting`, `lighting` and `blocking` were added to script generation on
2026-09-02. Every script created before that has none of them, and since the
video prompt reads exactly those fields to describe the world, those scripts
render against a background the model invents — the bland, non-cinematic look.

This is deliberately NOT a regenerate. A regenerate rewrites hook, shots,
dialogue and status, which would throw away comedy that already works and
knock approved scripts back to draft. This asks the model for the missing
environment ONLY, and merges it in:

  * writes `scene_direction` only when it is empty
  * writes per-shot `lighting`/`blocking` only where they are empty
  * never touches hook_line, dialogue, action, expression, camera, speaker,
    status, approval or the comedy judgment

So it is additive and safe to re-run: a second pass skips everything the
first one filled.

Usage:
    python scripts/backfill_script_environment.py --dry-run
    python scripts/backfill_script_environment.py
    python scripts/backfill_script_environment.py --limit 5
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(".env")

from app.db import SessionLocal  # noqa: E402
from app.models.character_variant import CharacterVariant  # noqa: E402
from app.models.toon_script import ToonScript  # noqa: E402
from app.services.culturetoon_script import (  # noqa: E402
    _call_llm_json,
    _format_script_for_prompt,
    label_speakers,
)


def _needs_backfill(script) -> bool:
    if not (script.scene_direction or "").strip():
        return True
    return any(
        not (shot or {}).get("lighting") or not (shot or {}).get("blocking")
        for shot in (script.shots or [])
    )


def _build_prompt(script, variants) -> str:
    shots = label_speakers(script.shots or [], variants)
    draft = _format_script_for_prompt(
        {"hook_line": script.hook_line, "shots": shots, "setting": script.scene_direction}
    )
    cast = ", ".join(f"{v.name} ({v.description or 'no description'})" for v in variants) or "unknown"
    numbers = [s.get("shot_number") for s in shots]

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

Every shot must appear. Output JSON only."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would change, write nothing")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    session = SessionLocal()
    filled = skipped = failed = 0
    try:
        scripts = (
            session.query(ToonScript)
            .filter(ToonScript.status != "archived")
            .order_by(ToonScript.updated_at.desc().nullslast())
            .all()
        )
        todo = [s for s in scripts if s.shots and _needs_backfill(s)]
        if args.limit:
            todo = todo[: args.limit]
        print(f"{len(scripts)} live scripts, {len(todo)} needing environment"
              f"{' (dry run)' if args.dry_run else ''}\n")

        for script in todo:
            variant_ids = {
                str(shot.get("speaker_variant_id"))
                for shot in script.shots or []
                if (shot or {}).get("speaker_variant_id")
            }
            variants = (
                session.query(CharacterVariant)
                .filter(CharacterVariant.id.in_(variant_ids))
                .all()
                if variant_ids else []
            )

            label = (script.hook_line or script.idea_text or str(script.id))[:60]
            try:
                result = _call_llm_json(_build_prompt(script, variants), temperature=0.6, max_tokens=1100)
            except Exception as exc:  # noqa: BLE001 - one bad script must not stop the run
                print(f"  FAILED  {label} — {exc}")
                failed += 1
                continue

            setting = (result.get("setting") or "").strip()
            by_number = {
                s.get("shot_number"): s
                for s in (result.get("shots") or [])
                if isinstance(s, dict)
            }

            changes = []
            if setting and not (script.scene_direction or "").strip():
                script.scene_direction = setting
                changes.append("setting")

            # Rebuilt as a new list: SQLAlchemy does not see in-place mutation
            # of a JSON column, so editing the dicts alone would commit nothing.
            new_shots = []
            lit = blocked = 0
            for shot in script.shots or []:
                shot = dict(shot or {})
                incoming = by_number.get(shot.get("shot_number")) or {}
                if not (shot.get("lighting") or "").strip() and (incoming.get("lighting") or "").strip():
                    shot["lighting"] = incoming["lighting"].strip()
                    lit += 1
                if not (shot.get("blocking") or "").strip() and (incoming.get("blocking") or "").strip():
                    shot["blocking"] = incoming["blocking"].strip()
                    blocked += 1
                new_shots.append(shot)
            if lit or blocked:
                script.shots = new_shots
                changes.append(f"lighting×{lit}")
                changes.append(f"blocking×{blocked}")

            if not changes:
                skipped += 1
                print(f"  skip    {label}")
                continue

            filled += 1
            print(f"  filled  {label}")
            print(f"          {', '.join(changes)}")
            if setting:
                print(f"          setting: {setting[:100]}")

        if args.dry_run:
            session.rollback()
            print(f"\nDry run — nothing written. Would fill {filled}, skip {skipped}, fail {failed}.")
        else:
            session.commit()
            print(f"\nDone. Filled {filled}, skipped {skipped}, failed {failed}.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
