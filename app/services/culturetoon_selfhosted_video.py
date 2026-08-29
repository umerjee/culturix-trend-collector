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
import os
import random
import subprocess
import tempfile
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


def build_prompt_from_script(script, background=None) -> str:
    """script: a ToonScript ORM object (shots/hook_line already populated).
    Folds hook_line + each shot's visual/action/expression/dialogue into
    one descriptive prompt string for a single continuous LTX generation.

    background: an optional ToonBackground ORM object (or anything with
    .name/.description attributes) — confirmed live 2026-08-30: this
    pipeline never referenced Toon.background_id/ToonScript.background_id
    at all, so a selected Location was silently dropped from the video
    prompt entirely regardless of which one was chosen. Prepended once,
    before the per-shot beats, rather than per-shot, since one location
    covers a whole script here (this pipeline doesn't do per-shot location
    changes)."""
    parts = []
    if background is not None:
        name = (getattr(background, "name", None) or "").strip()
        description = (getattr(background, "description", None) or "").strip()
        if name or description:
            parts.append(f"Set in {name}" + (f": {description}" if description else "") if name else description)
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
        expression = (shot.get("expression") or "").strip()
        dialogue = (shot.get("dialogue") or "").strip()
        delivery = (shot.get("dialogue_delivery") or "").strip()
        if visual:
            parts.append(visual)
        if action:
            parts.append(action)
        if expression:
            # Confirmed live 2026-08-30: every shot in a real script
            # carries its own expression field, but it was never being
            # read here at all — dropped silently regardless of what the
            # script actually called for.
            parts.append(f"with a {expression.lower()} expression")
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


def _gather_dialogue(script) -> str:
    """Joins every shot's dialogue line, in order, into one narration
    script — this pipeline generates one continuous clip (no per-shot
    cuts, see module docstring), so audio is synthesized as one
    continuous narration track rather than per-shot lines that would need
    cut boundaries this pipeline doesn't have."""
    lines = [(shot.get("dialogue") or "").strip() for shot in (script.shots or [])]
    return " ... ".join(line for line in lines if line)


def _synthesize_narration_elevenlabs(script, api_key: str, voice_id: str) -> bytes:
    """Per-shot ElevenLabs synthesis concatenated into one track — mirrors
    app/services/culturetoon_video.py::_dub_dialogue exactly (the Kling
    path's own ElevenLabs integration), reused here so self-hosted
    narration quality matches what Kling-path users already get when a
    brand has ElevenLabs configured. Confirmed live 2026-08-30: the
    self-hosted path was instead always using edge-tts's single free
    generic voice (en-US-AriaNeural, hardcoded, no per-character casting)
    regardless of what voice_provider/elevenlabs_voice_id a variant had
    set — a real, noticeable quality gap versus Kling's own native voice
    or its ElevenLabs fallback."""
    from app.media.elevenlabs_voice import ElevenLabsProvider, ElevenLabsError

    if not voice_id:
        raise ElevenLabsError("voice_provider is 'elevenlabs' but the character variant has no elevenlabs_voice_id set")

    provider = ElevenLabsProvider(api_key)
    with tempfile.TemporaryDirectory() as tmp_dir:
        segment_paths = []
        for i, shot in enumerate(script.shots or []):
            dialogue = (shot.get("dialogue") or "").strip()
            if not dialogue:
                continue
            audio_bytes = provider.synthesize(dialogue, voice_id)
            seg_path = os.path.join(tmp_dir, f"seg_{i}.mp3")
            with open(seg_path, "wb") as f:
                f.write(audio_bytes)
            segment_paths.append(seg_path)

        if not segment_paths:
            raise ElevenLabsError("No dialogue segments to synthesize")

        list_path = os.path.join(tmp_dir, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in segment_paths:
                f.write(f"file '{p}'\n")
        audio_path = os.path.join(tmp_dir, "narration.mp3")
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", audio_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise ElevenLabsError(f"ffmpeg failed concatenating narration segments: {result.stderr[-1000:]}")
        with open(audio_path, "rb") as f:
            return f.read()


def _synthesize_narration(script, variants: list, elevenlabs_api_key: Optional[str] = None) -> Optional[bytes]:
    """Returns MP3 bytes for the script's full dialogue, or None if the
    script has no dialogue at all (a pure-action/silent script) since
    there'd be nothing to narrate.

    Uses ElevenLabs (per-shot synthesis, same as the Kling path) when the
    primary cast member opts into it (variant.voice_provider ==
    "elevenlabs") AND the caller supplied a decrypted brand API key AND
    the variant has an elevenlabs_voice_id set — otherwise falls back to
    the free edge-tts provider already used by the trend engine's faceless
    reels (app/media/voice.py), same fail-open philosophy as the Kling
    path's own voice_provider handling in culturetoon_video.py. Best-
    effort throughout: a synthesis failure degrades to a silent video
    rather than failing a generation that would otherwise succeed."""
    from app.media.voice import EdgeTTSProvider

    dialogue = _gather_dialogue(script)
    if not dialogue:
        return None

    primary_variant = variants[0] if variants else None
    use_elevenlabs = (
        primary_variant is not None
        and getattr(primary_variant, "voice_provider", None) == "elevenlabs"
        and elevenlabs_api_key
        and getattr(primary_variant, "elevenlabs_voice_id", None)
    )
    if use_elevenlabs:
        try:
            return _synthesize_narration_elevenlabs(script, elevenlabs_api_key, primary_variant.elevenlabs_voice_id)
        except Exception:
            logger.warning("ElevenLabs narration failed — falling back to edge-tts", exc_info=True)

    try:
        result = EdgeTTSProvider().synthesize(dialogue)
        return result.asset_bytes
    except Exception:
        logger.warning("Narration synthesis failed — video will be delivered silent", exc_info=True)
        return None


def _probe_audio_duration_seconds(audio_bytes: bytes) -> Optional[float]:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_bytes)
        path = f.name
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def generate_toon_video_selfhosted(script, variants: list, endpoint_id: str,
                                    duration_seconds: Optional[float] = None,
                                    use_allocation_retry: bool = False,
                                    background=None,
                                    elevenlabs_api_key: Optional[str] = None) -> bytes:
    """Returns raw video bytes for the caller to persist via
    app.media.storage.upload(). Raises SelfHostedVideoGenerationError (cast
    not ready) or whatever app.media.runpod_serverless_client/ltx_workflow
    raise on a Serverless-side failure.

    use_allocation_retry: set by the batch runner for only the first job of
    a scheduled window (app/services/culturetoon_selfhosted_batch.py) —
    routes through run_inference_job_with_allocation_retry instead of the
    plain call, since a cold Serverless endpoint failing to allocate a
    worker is a distinct failure mode from an individual clip's own
    generation failing.

    background: the resolved ToonBackground for this script (see
    build_prompt_from_script) — this function doesn't resolve it itself
    (no DB session assumption here, callers already have one), so a
    caller that wants Location context in the prompt must fetch and pass
    it explicitly.

    elevenlabs_api_key: the primary cast member's brand's own decrypted
    ElevenLabs key, when voice_provider="elevenlabs" — this function
    doesn't resolve or decrypt it itself (same no-DB-session reasoning as
    background above), so a caller that wants ElevenLabs narration instead
    of the edge-tts fallback must fetch and decrypt it explicitly (see
    generate_video_for_toon_selfhosted and culturetoon_selfhosted_batch.py
    for the two existing examples, both mirroring app/services/
    culturetoon_video.py's identical decrypt-and-pass pattern)."""
    import httpx
    from app.media import ltx_workflow, runpod_serverless_client

    lora_path = resolve_ready_lora(variants)
    prompt_text = build_prompt_from_script(script, background=background)
    total_duration = (
        duration_seconds
        or script.total_duration_seconds
        or sum(s.get("duration_seconds", 0) for s in (script.shots or []))
        or 5
    )

    # This pipeline generated silent video only until now — no equivalent
    # to Kling Omni's native audio/lip-sync. Synthesizing narration BEFORE
    # requesting the video (rather than after) lets the real synthesized
    # length drive the requested video duration, so the two land close in
    # total runtime instead of the video's length being a pure guess from
    # script.total_duration_seconds while the narration runs whatever
    # length the dialogue actually takes to speak. Only does this when the
    # CALLER didn't already pass an explicit duration_seconds — an
    # explicit override (e.g. a caller deliberately requesting a shorter
    # clip to stay under this GPU tier's VRAM ceiling) must win, or a
    # long-dialogue script would silently blow the override right back up
    # to its full narrated length.
    narration_bytes = _synthesize_narration(script, variants, elevenlabs_api_key=elevenlabs_api_key)
    if narration_bytes and duration_seconds is None:
        narration_duration = _probe_audio_duration_seconds(narration_bytes)
        if narration_duration:
            total_duration = narration_duration

    # Explicit random seed — confirmed live 2026-08-28: with no seed
    # passed, build_workflow() leaves the template's hardcoded seed=0 in
    # place, so any two calls with identical prompt/duration/lora (e.g.
    # retrying the same Toon, which is the normal shape of a failed-then-
    # retried generation) produce byte-identical ComfyUI inputs. ComfyUI
    # then serves a server-side CACHED result instead of re-executing —
    # and its /history response for a fully-cached prompt leaves
    # `outputs` empty even though status_str is "success", which
    # handler.py's _download_output_bytes can't extract a file from
    # ("No file output found in ComfyUI history entry"). A random seed
    # per call sidesteps the whole cache-hit class rather than patching
    # the worker's output-extraction logic for an edge case production
    # never actually wants (identical output on retry isn't desirable
    # here anyway).
    # Confirmed live 2026-08-29/30: pure text-to-video with only a
    # character LoRA for identity (the LoRA trained on static reference
    # images, never on motion) produced a video that was really just 2-3
    # held poses with abrupt transitions between them, not continuous
    # animation — asking one LoRA to carry both identity AND not break the
    # base model's motion generation turned out to be a harder ask than
    # the ecosystem is actually built for. Anchoring the first frame on
    # the primary cast member's own real photo via image-to-video (LTX's
    # own documented, well-supported pattern) grounds identity from the
    # photo instead, leaving the base model free to generate motion
    # naturally from that anchor. Best-effort: if the photo can't be
    # fetched for any reason, fall back to the old empty-latent path
    # rather than failing the whole generation over a missing image.
    reference_image_bytes = None
    reference_image_url = variants[0].image_url if variants else None
    if reference_image_url:
        try:
            reference_image_bytes = httpx.get(reference_image_url, timeout=30).content
        except Exception:
            logger.warning("Failed to fetch reference image %s — falling back to text-to-video", reference_image_url, exc_info=True)

    workflow = ltx_workflow.build_workflow(
        prompt_text, total_duration, lora_path=lora_path, seed=random.randint(1, 2**31 - 1),
        reference_image_filename="reference.png" if reference_image_bytes else None,
    )
    # narration_bytes, when present, is sent along with the job and muxed
    # onto the video by the RunPod worker itself (deploy/runpod_serverless/
    # handler.py::_mux_narration_audio) — encoding happens directly on
    # RunPod instead of this function downloading a silent video and
    # running a separate local ffmpeg pass, so what comes back here is
    # already the final dubbed file (or the silent one, if muxing failed
    # server-side — see that function's own best-effort fallback).
    if use_allocation_retry:
        video_bytes = runpod_serverless_client.run_inference_job_with_allocation_retry(
            endpoint_id, workflow, reference_image_bytes=reference_image_bytes,
            narration_audio_bytes=narration_bytes,
        )
    else:
        video_bytes = runpod_serverless_client.run_inference_job(
            endpoint_id, workflow, reference_image_bytes=reference_image_bytes,
            narration_audio_bytes=narration_bytes,
        )
    return video_bytes


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
    from app.models.toon_background import ToonBackground
    from app.models.character_variant import CharacterVariant
    from app.models.character_brand import CharacterBrand
    from app.media import storage, runpod_serverless_client
    from app.services.culturetoon_usage import record_usage, estimate_selfhosted_video_cost
    from app.social.crypto import decrypt
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
        # Confirmed live 2026-08-30: neither Toon.background_id nor
        # ToonScript.background_id was ever read here at all, so a
        # selected Location never reached the video prompt regardless of
        # which one was chosen. script's own background_id wins (a
        # script's setting drives its background per that column's own
        # docstring), falling back to the Toon's.
        background = None
        background_id = script.background_id or toon.background_id
        if background_id:
            background = session.query(ToonBackground).filter_by(id=background_id).first()

        # Confirmed live 2026-08-30: this path always used edge-tts's one
        # free generic voice, regardless of what voice_provider/
        # elevenlabs_voice_id a variant had — a real quality gap versus
        # what the Kling path already offers. Same resolve-and-decrypt
        # pattern as app/services/culturetoon_video.py::generate_video_
        # for_toon: the primary cast member drives voice_provider for the
        # whole video, and a missing/absent brand key fails open to
        # edge-tts rather than blocking generation.
        elevenlabs_api_key = None
        if variants and variants[0].voice_provider == "elevenlabs":
            brand = session.query(CharacterBrand).filter_by(id=toon.brand_id).first()
            if brand and brand.elevenlabs_api_key_encrypted:
                elevenlabs_api_key = decrypt(brand.elevenlabs_api_key_encrypted)

        video_bytes = generate_toon_video_selfhosted(
            script, variants, endpoint_id, duration_seconds=duration, use_allocation_retry=True,
            background=background, elevenlabs_api_key=elevenlabs_api_key,
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
