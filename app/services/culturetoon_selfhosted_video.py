"""Self-hosted (RunPod Serverless + ComfyUI + LTX-2) counterpart to
app/services/culturetoon_video.py's Kling Omni path. Builds one LTX prompt
from a ToonScript's shots and resolves the cast's trained LoRA, then
submits the workflow to the RunPod Serverless inference endpoint
(app/media/runpod_serverless_client.py) — no pod lifecycle to manage here,
Serverless scales itself.

Known simplification vs. the Kling Omni path: there's no equivalent to
Kling's multi-shot DSL (build_kling_prompt) here, so a script's shots are
folded into one continuous prompt rather than driving per-shot cuts — v1
produces one continuous clip. Also, ComfyUI's LoraLoader takes one LoRA per
generation, so a multi-character script's video is only grounded in the
PRIMARY (first-listed) cast member's trained identity; the rest are
described in the prompt text only, not visually locked in the way Kling
Omni's per-character Elements allow.

Two callers, two different DB-write shapes: app/services/
culturetoon_selfhosted_batch.py creates a brand-new Toon per approved
script (the scheduled/pilot-brand path); generate_video_for_toon_selfhosted
below instead operates on an EXISTING Toon, the interactive "Generate
video" button's self-hosted branch (app/routers/culturetoons.py's
generate_toon_video, dispatching here instead of
culturetoon_video.generate_video_for_toon when the toon's primary cast
member has a ready LoRA). No QA run here yet (unlike the Kling path) —
out of scope for wiring the button; QA parity for self-hosted can follow
separately.
"""
import logging
import time
import uuid as _uuid
from typing import Optional

logger = logging.getLogger("culturix.services.culturetoon_selfhosted_video")

_COMMIT_RETRY_ATTEMPTS = 6
_COMMIT_RETRY_BACKOFF_SECONDS = 15


class SelfHostedVideoGenerationError(Exception):
    pass


def _resilient_commit(session, mutate) -> None:
    """Confirmed live 2026-08-26, twice in a row: this module holds one
    SessionLocal() open across the whole generation attempt, including
    RunPod's own allocation-retry wait (up to 600s+ per attempt). The
    connection can go stale server-side during that wait (Supabase/pgbouncer
    idle timeout) — pool_pre_ping only catches a stale connection at
    checkout, not one that dies while just sitting open — so the exact
    commit meant to record the *original* failure (RunPodServerlessError/
    TimeoutError) instead raised its own unrelated psycopg2.OperationalError
    and masked it, leaving the Toon stuck in status='animating' forever.

    Takes `mutate` (re-applies the intended field assignments) rather than
    just retrying a bare commit() — confirmed live in this fix's own test:
    session.rollback() expires every object in the session by default, so a
    naive "rollback, then commit() again" retry silently commits *nothing*,
    since the in-memory attribute changes set before the first failed
    commit are gone the moment rollback() runs. Re-running `mutate` each
    attempt (idempotent field assignments, safe to repeat) is what actually
    makes the retry do something."""
    last_exc = None
    for attempt in range(_COMMIT_RETRY_ATTEMPTS):
        try:
            mutate()
            session.commit()
            return
        except Exception as exc:
            last_exc = exc
            session.rollback()
            logger.warning(
                "session.commit() attempt %d/%d failed: %s",
                attempt + 1, _COMMIT_RETRY_ATTEMPTS, exc,
            )
            if attempt < _COMMIT_RETRY_ATTEMPTS - 1:
                time.sleep(_COMMIT_RETRY_BACKOFF_SECONDS)
    raise last_exc


def build_prompt_from_script(script) -> str:
    """script: a ToonScript ORM object (shots/hook_line already populated).
    Folds hook_line + each shot's visual/action/dialogue into one
    descriptive prompt string for a single continuous LTX generation."""
    parts = []
    if script.hook_line:
        parts.append(script.hook_line.strip())
    for shot in script.shots or []:
        # shot_type/camera_movement don't produce discrete cuts here the
        # way they do in Kling's multi-shot DSL (this whole loop still
        # folds into ONE continuous clip, see module docstring) — but
        # still useful descriptive signal for framing/movement within
        # that one continuous generation.
        shot_type = shot.get("shot_type")
        if shot_type:
            parts.append(f"{shot_type.replace('_', ' ')} shot")
        camera_movement = shot.get("camera_movement")
        if camera_movement:
            parts.append(f"{camera_movement.replace('_', ' ')} camera movement")
        visual = (shot.get("visual") or "").strip()
        action = (shot.get("action") or "").strip()
        dialogue = (shot.get("dialogue") or "").strip()
        delivery = (shot.get("dialogue_delivery") or "").strip()
        if visual:
            parts.append(visual)
        if action:
            parts.append(action)
        if dialogue:
            parts.append(f'saying "{dialogue}"' + (f" ({delivery} delivery)" if delivery else ""))
    return ". ".join(p for p in parts if p) or "A character reacts to their day."


def resolve_ready_lora(variants: list) -> str:
    """variants: the script's full cast (CharacterVariant ORM objects).
    Raises SelfHostedVideoGenerationError if ANY cast member's lora_status
    isn't "ready" — a script isn't generated with an inconsistent-looking
    character silently substituted in, same philosophy as
    generate_video_for_toon's own element_status check for Kling Omni.
    Returns the primary (first-listed) cast member's lora_path — see this
    module's docstring on the single-LoRA-per-generation limitation."""
    not_ready = [v.name for v in variants if v.lora_status != "ready"]
    if not_ready:
        raise SelfHostedVideoGenerationError(
            f"Character(s) not ready for self-hosted generation (no trained LoRA): {', '.join(not_ready)}"
        )
    return variants[0].lora_path


def generate_toon_video_selfhosted(script, variants: list, endpoint_id: str,
                                    duration_seconds: Optional[float] = None,
                                    use_allocation_retry: bool = False) -> bytes:
    """Returns raw video bytes for the caller to persist via
    app.media.storage.upload(). Raises SelfHostedVideoGenerationError (cast
    not ready) or whatever app.media.runpod_serverless_client/ltx_workflow
    raise on a Serverless-side failure.

    use_allocation_retry: set by the batch runner for only the first job of
    a scheduled window (app/services/culturetoon_selfhosted_batch.py) —
    routes through run_inference_job_with_allocation_retry instead of the
    plain call, since a cold Serverless endpoint failing to allocate a
    worker is a distinct failure mode from an individual clip's own
    generation failing."""
    from app.media import ltx_workflow, runpod_serverless_client

    lora_path = resolve_ready_lora(variants)
    prompt_text = build_prompt_from_script(script)
    total_duration = (
        duration_seconds
        or script.total_duration_seconds
        or sum(s.get("duration_seconds", 0) for s in (script.shots or []))
        or 5
    )

    workflow = ltx_workflow.build_workflow(prompt_text, total_duration, lora_path=lora_path)
    if use_allocation_retry:
        return runpod_serverless_client.run_inference_job_with_allocation_retry(endpoint_id, workflow)
    return runpod_serverless_client.run_inference_job(endpoint_id, workflow)


def generate_video_for_toon_selfhosted(user_id, toon_id) -> None:
    """Interactive-button counterpart to culturetoon_video.py's
    generate_video_for_toon, called the same way (backgrounded from
    POST /toons/{id}/generate-video) but against the self-hosted path.
    Owns the whole existing-Toon DB-write lifecycle itself, unlike
    generate_toon_video_selfhosted() above which just returns bytes —
    every call here is a single ad-hoc click, not a batch window, so it
    always uses the allocation-retry client (a cold Serverless endpoint
    can't be assumed warm the way the batch runner can assume for jobs
    after its own first one)."""
    from app.db import SessionLocal
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript
    from app.models.character_variant import CharacterVariant
    from app.media import storage, runpod_serverless_client
    from app.services.culturetoon_usage import record_usage, estimate_selfhosted_video_cost
    import os

    session = SessionLocal()
    toon = None
    duration = 0
    try:
        toon = session.query(Toon).filter_by(id=_uuid.UUID(str(toon_id))).first()
        if not toon:
            return

        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        if not script:
            raise ValueError("Toon's script is missing")

        cast_ids = [str(v) for v in (script.character_variant_ids or [])]
        if not cast_ids and script.character_variant_id:
            cast_ids = [str(script.character_variant_id)]
        if not cast_ids:
            cast_ids = [str(toon.character_variant_id)]
        variants = session.query(CharacterVariant).filter(
            CharacterVariant.id.in_([_uuid.UUID(v) for v in cast_ids])
        ).all()
        variants_by_id = {str(v.id): v for v in variants}
        missing = [vid for vid in cast_ids if vid not in variants_by_id]
        if missing:
            raise ValueError(f"Character variant(s) not found: {missing}")
        # Preserve script cast order (resolve_ready_lora treats index 0 as
        # primary/visually-grounded) rather than whatever order the DB
        # query happened to return.
        variants = [variants_by_id[vid] for vid in cast_ids]

        endpoint_id = os.getenv("RUNPOD_SERVERLESS_ENDPOINT_ID", "")
        if not endpoint_id:
            raise ValueError("RUNPOD_SERVERLESS_ENDPOINT_ID is not configured")

        toon.status = "animating"
        toon.generation_error = None
        toon.video_provider = "self_hosted"
        session.commit()

        duration = (
            script.total_duration_seconds
            or sum(s.get("duration_seconds", 0) for s in (script.shots or []))
            or 5
        )
        video_bytes = generate_toon_video_selfhosted(
            script, variants, endpoint_id, duration_seconds=duration, use_allocation_retry=True,
        )

        video_url = storage.upload(
            video_bytes, f"culturetoons/{toon.brand_id}/toons/{toon.id}/raw-{_uuid.uuid4().hex[:8]}.mp4", "video/mp4",
        )
        # Same "archive, don't discard" fix as the Kling path — regenerating
        # an existing toon (only possible from the interactive button, the
        # batch runner never regenerates) used to silently lose whatever
        # take was there before.
        previous_url = toon.final_video_url or toon.raw_video_url

        def _apply_success():
            if previous_url:
                toon.previous_video_urls = (toon.previous_video_urls or []) + [previous_url]
            toon.raw_video_url = video_url
            toon.final_video_url = video_url
            toon.status = "ready"

        _resilient_commit(session, _apply_success)
        logger.info("Self-hosted video generation complete for toon %s", toon_id)

    except (ValueError, SelfHostedVideoGenerationError, runpod_serverless_client.RunPodServerlessError, TimeoutError) as exc:
        session.rollback()
        if toon:
            error_text = str(exc)[:2000]

            def _apply_failure():
                toon.status = "failed"
                toon.generation_error = error_text

            _resilient_commit(session, _apply_failure)
        logger.warning("Self-hosted generation failed for toon %s: %s", toon_id, exc)
    except Exception as exc:
        session.rollback()
        if toon:
            error_text = f"Unexpected error: {exc}"[:2000]

            def _apply_unexpected_failure():
                toon.status = "failed"
                toon.generation_error = error_text

            _resilient_commit(session, _apply_unexpected_failure)
        logger.exception("Self-hosted generation failed unexpectedly for toon %s", toon_id)
    finally:
        if toon:
            def _apply_usage():
                # Recorded regardless of outcome, same reasoning as the
                # batch runner's own record_usage call — a failed
                # generation still burns GPU time. record_usage() adds a
                # new row rather than mutating a tracked one, so it must be
                # re-run (not just the commit) on every retry attempt too —
                # a rollback discards a pending-but-uncommitted insert
                # entirely, it doesn't leave it around to recommit.
                record_usage(
                    session, user_id=user_id, brand_id=toon.brand_id, toon_id=toon.id,
                    provider="runpod_ltx", generation_type="toon_video_selfhosted",
                    output_units=int(duration), cost_usd=estimate_selfhosted_video_cost(duration),
                )

            _resilient_commit(session, _apply_usage)
        session.close()
