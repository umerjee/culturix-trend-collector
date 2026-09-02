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
from app.services.culturetoon_environment import (  # noqa: E402
    apply_environment,
    generate_environment,
    needs_environment,
    EnvironmentGenerationError,
)


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
        todo = [s for s in scripts if s.shots and needs_environment(s)]
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
                result = generate_environment(script, variants)
            except EnvironmentGenerationError as exc:
                # One bad script must not stop the run.
                print(f"  FAILED  {label} — {exc}")
                failed += 1
                continue

            # overwrite=False: never clobber anything already written, so
            # this is safe to re-run.
            changes = apply_environment(script, result, overwrite=False)
            setting = script.scene_direction or ""

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
