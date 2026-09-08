"""Self-hosted (RunPod Serverless + ComfyUI + LTX-2) counterpart to
app/services/culturetoon_video.py's Kling Omni path. Builds one LTX
generation PER SHOT (each with its own camera_movement/shot_type prompt
and its own speaker's identity/LoRA) and submits the whole list to the
RunPod Serverless inference endpoint (app/media/runpod_serverless_client.py)
as one job — the worker itself loops through shots sequentially (keeping
the model resident in GPU memory across all of them) and concatenates the
results, rather than this backend submitting N separate jobs. No pod
lifecycle to manage here, Serverless scales itself.

Confirmed live 2026-08-30: earlier versions of this module folded every
shot into ONE continuous prompt for a single LTX generation, so
shot_type/camera_movement were only descriptive text within one
unbroken take rather than producing real cuts — and a multi-character
script was only ever visually grounded in the PRIMARY (first-listed)
cast member, since one generation call takes one LoRA. Real per-shot
generation fixes both: each shot in script.shots that carries its own
`speaker_variant_id` (already present on every real multi-character
script — see _resolve_shot_variant) now anchors on THAT character's own
photo/LoRA, and shot_type/camera_movement drive an actual distinct camera
setup per cut instead of shared descriptive text in one clip.

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
import re
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


def _expand_visual_style(visual_style: str) -> str:
    """ToonBackground.visual_style stores a SLUG ("cinematic_cultural"),
    not prose — the UI's own dropdown (culturix-web's BackgroundGallery /
    ScriptManager, DEFAULT_BACKGROUND_STYLE) writes the key, and
    app/routers/culturetoons.py's ART_STYLES maps it to the real
    descriptive prompt text. Confirmed live 2026-09-01 that every existing
    Location row stores the bare slug, so passing it straight through would
    put the literal token "cinematic_cultural" into an LTX prompt, which is
    noise rather than art direction. Falls back to a readability-cleaned
    version of the raw value for any slug not in ART_STYLES (e.g. a
    hand-written style string), rather than dropping it."""
    from app.routers.culturetoons import ART_STYLES

    style = ART_STYLES.get(visual_style)
    if style and style.get("prompt"):
        return style["prompt"]
    return visual_style.replace("_", " ")


# Deliberately style-NEUTRAL: asserts render quality only, never an art
# style. The art style comes from the Location's own visual_style (see
# _expand_visual_style) and from the character LoRA. An earlier version of
# this suffix hardcoded "3D animated cartoon in a polished Pixar-style
# render", which directly contradicted the "semi-realistic painterly ...
# (not photoreal)" text that the cinematic_cultural style expands to —
# two opposing art directions in one prompt is exactly the kind of
# conflicting instruction that produces incoherent output.
_QUALITY_SUFFIX = (
    "Smooth natural motion, stable consistent facial features throughout, "
    "clean expressive character animation. Sharp focus on the character's face, "
    "consistent lighting, high detail, crisp film-quality render"
)

# The character-quality suffix actively contradicts a subject shot: asking for
# "sharp focus on the character's face" in a frame that must contain no people
# invites the model to put one back in.
_SUBJECT_QUALITY_SUFFIX = (
    "Smooth natural camera motion, cinematic scale and depth, "
    "consistent lighting, high detail, crisp film-quality render"
)


def _build_shot_prompt(shot: dict, background=None) -> str:
    """One shot's own prompt text — shot_type/camera_movement describe
    THIS shot's distinct camera setup (each shot is now its own separate
    LTX generation, see module docstring), not shared text folded into one
    continuous clip. Returns "" (not a fallback phrase) for a shot with no
    usable fields at all — callers decide their own fallback, since
    build_prompt_from_script (whole-script text) and the per-shot
    generation loop (needs a non-empty prompt for LTX) want different
    defaults."""
    parts = []
    if background is not None:
        name = (getattr(background, "name", None) or "").strip()
        description = (getattr(background, "description", None) or "").strip()
        if name or description:
            parts.append(f"Set in {name}" + (f": {description}" if description else "") if name else description)
        # visual_style/country are real ToonBackground columns that were
        # never read here — only name/description were, so a Location's
        # own art direction and place never reached the prompt at all
        # (same class of silent drop as the `expression` field, fixed
        # 2026-08-30). Note the self-hosted path can't use the Location's
        # image_url as a true visual reference the way the Kling path does
        # (culturetoon_video.py sends it as a second `refer_image`) — LTX
        # image-to-video takes exactly ONE first-frame anchor, and that
        # slot is already the speaking character's own photo, which
        # matters more for identity. Text is the only channel available
        # for the setting here, so use all of it.
        country = (getattr(background, "country", None) or "").strip()
        if country:
            parts.append(f"Located in {country}")
        visual_style = (getattr(background, "visual_style", None) or "").strip()
        if visual_style:
            parts.append(_expand_visual_style(visual_style))
    shot_type = shot.get("shot_type")
    if shot_type:
        parts.append(f"{shot_type.replace('_', ' ')} shot")
    camera_movement = shot.get("camera_movement")
    if camera_movement:
        parts.append(f"{camera_movement.replace('_', ' ')} camera movement")
    visual = (shot.get("visual") or "").strip()
    action = (shot.get("action") or "").strip()
    expression = (shot.get("expression") or "").strip()
    # lighting/blocking are newer shot fields (see culturetoon_script.py's
    # schema). Reading them here matters as much as generating them — the
    # `expression` field was generated but silently dropped for weeks, and
    # the same would happen to these. Lighting with a stated DIRECTION is
    # what makes separate shots read as one continuous scene rather than
    # unrelated clips; blocking + held props keep characters distinguishable
    # when faces are small or moving, which matters more now that identity
    # is carried by a first-frame anchor rather than a per-character LoRA.
    lighting = (shot.get("lighting") or "").strip()
    blocking = (shot.get("blocking") or "").strip()
    dialogue = (shot.get("dialogue") or "").strip()
    delivery = (shot.get("dialogue_delivery") or "").strip()
    # A "subject" shot is ON the thing being discussed, with nobody in frame.
    # Without this the schema could only ever describe a character performing,
    # which is why every video came out as a talking head in front of a
    # background — the black hole was never actually shown.
    focus = (shot.get("shot_focus") or "character").strip().lower()
    subject_visual = (shot.get("subject_visual") or "").strip()
    if focus == "subject" and subject_visual:
        parts.append(subject_visual)
        parts.append(
            "No people in frame at all — this shot is entirely on the subject, "
            "no character visible, no face, no body"
        )
        if lighting:
            parts.append(lighting)
        if dialogue:
            # Voice over a subject shot: the line is heard, the speaker isn't seen.
            parts.append(
                f'a voice is heard over this shot saying "{dialogue}"'
                + (f" ({delivery} delivery)" if delivery else "")
                + ", the speaker is off screen and not visible"
            )
        else:
            # Same joint-audio trap as a silent character shot: with no line
            # and nothing asking for silence, the model invents narration.
            parts.append(
                "No one speaks in this shot — no dialogue, no voice-over, ambient sound only"
            )
        return ". ".join(p for p in parts if p) + ". " + _SUBJECT_QUALITY_SUFFIX

    if focus == "both" and subject_visual:
        parts.append(subject_visual)
    if visual:
        parts.append(visual)
    if blocking:
        parts.append(blocking)
    if lighting:
        parts.append(lighting)
    if action:
        parts.append(action)
    if expression:
        # Confirmed live 2026-08-30: every shot in a real script carries
        # its own expression field, but it was never being read here at
        # all — dropped silently regardless of what the script called for.
        parts.append(f"with a {expression.lower()} expression")
    if dialogue:
        parts.append(f'saying "{dialogue}"' + (f" ({delivery} delivery)" if delivery else ""))
    if not parts:
        return ""
    # Quality/style suffix. Confirmed live 2026-09-01 against real output:
    # the terse fragment-joined prompt this used to return left LTX almost
    # no guidance on RENDER quality (only on content), and the result showed
    # exactly the failure modes an underspecified prompt invites — ghosting
    # around a character's head, smeared facial features, an overall soft
    # "melted" look. LTX's own prompting guidance is that it responds to
    # descriptive, camera-and-lighting-aware language rather than terse
    # keyword lists, so this appends a consistent cinematic framing to every
    # shot instead of leaving render quality entirely unspecified. Paired
    # with ltx_workflow.DEFAULT_NEGATIVE_PROMPT, which steers away from the
    # same artifacts from the other direction.
    return ". ".join(p for p in parts if p) + ". " + _QUALITY_SUFFIX


def build_prompt_from_script(script, background=None) -> str:
    """script: a ToonScript ORM object (shots/hook_line already populated).
    Folds hook_line + every shot's own prompt text into one descriptive
    whole-script string — used for logging/preview, NOT for generation
    itself anymore (generate_toon_video_selfhosted builds one prompt PER
    SHOT via _build_shot_prompt so each drives its own distinct camera cut,
    see module docstring).

    background: an optional ToonBackground ORM object (or anything with
    .name/.description attributes) — confirmed live 2026-08-30: this
    pipeline never referenced Toon.background_id/ToonScript.background_id
    at all, so a selected Location was silently dropped from the video
    prompt entirely regardless of which one was chosen. Prepended once
    here (whole-script summary), though the actual per-shot generation
    loop repeats it on every shot since each is now an independent
    generation that needs its own scene-setting context."""
    parts = []
    if background is not None:
        name = (getattr(background, "name", None) or "").strip()
        description = (getattr(background, "description", None) or "").strip()
        if name or description:
            parts.append(f"Set in {name}" + (f": {description}" if description else "") if name else description)
    if script.hook_line:
        parts.append(script.hook_line.strip())
    for shot in script.shots or []:
        shot_prompt = _build_shot_prompt(shot)
        if shot_prompt:
            parts.append(shot_prompt)
    return ". ".join(p for p in parts if p) or "A character reacts to their day."


def _resolve_shot_variant(shot: dict, variants: list):
    """Which cast member's identity/LoRA anchors THIS shot's own
    generation. Real multi-character scripts already carry a
    speaker_variant_id per shot (confirmed live 2026-08-30 on a real
    3-character script) — falls back to the primary (first-listed) cast
    member for shots with no speaker (e.g. a wordless reaction shot with
    multiple characters on screen) or an id that doesn't match any
    resolved cast member."""
    speaker_id = shot.get("speaker_variant_id")
    if speaker_id:
        for v in variants:
            if str(v.id) == str(speaker_id):
                return v
    return variants[0] if variants else None


def resolve_ready_lora(variants: list) -> str:
    """variants: the script's full cast (CharacterVariant ORM objects).
    Raises SelfHostedVideoGenerationError if ANY cast member's lora_status
    isn't "ready" — a script isn't generated with an inconsistent-looking
    character silently substituted in, same philosophy as
    generate_video_for_toon's own element_status check for Kling Omni.
    Returns the primary (first-listed) cast member's lora_path — used only
    as the DEFAULT shot anchor now (see _resolve_shot_variant); most shots
    resolve their own speaker's LoRA independently."""
    not_ready = [v.name for v in variants if v.lora_status != "ready"]
    if not_ready:
        raise SelfHostedVideoGenerationError(
            f"Character(s) not ready for self-hosted generation (no trained LoRA): {', '.join(not_ready)}"
        )
    return variants[0].lora_path


def _gather_dialogue(script) -> str:
    """Joins every shot's dialogue line, in order, into one narration
    script. Narration is still synthesized as ONE continuous track (not
    per-shot lines cut to each shot's own boundary) even though video
    generation itself is now per-shot (see module docstring) — the final
    mux (deploy/runpod_serverless/handler.py) lays this one track over the
    whole concatenated video with -shortest, same simplification
    app/services/culturetoon_video.py::_dub_dialogue already accepts for
    the Kling path (dialogue placed sequentially, not time-aligned to each
    shot's exact boundary)."""
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


def _resolve_narration(script, variants: list, elevenlabs_api_key: Optional[str] = None) -> tuple:
    """Returns (narration_audio_bytes, narration_text) — exactly one is set
    (or both None if the script has no dialogue at all, a pure-action/
    silent script). ElevenLabs (per-shot synthesis, same as the Kling
    path) is still synthesized HERE on the backend, since it's a paid
    opt-in driven by the caller's own decrypted brand credential. The
    default (free) path instead returns the raw gathered dialogue TEXT for
    the RunPod worker's own GPU to synthesize via Chatterbox
    (deploy/runpod_serverless/handler.py) — moved off edge-tts (which ran
    on THIS backend, not RunPod, and was a noticeably worse single generic
    voice) after real research confirmed 2026-08-30 that Chatterbox
    (Resemble AI, MIT-licensed) beat ElevenLabs outright in blind listening
    tests, at zero marginal cost since it reuses the same GPU already
    being paid for by this job's video generation."""
    dialogue = _gather_dialogue(script)
    if not dialogue:
        return None, None

    primary_variant = variants[0] if variants else None
    use_elevenlabs = (
        primary_variant is not None
        and getattr(primary_variant, "voice_provider", None) == "elevenlabs"
        and elevenlabs_api_key
        and getattr(primary_variant, "elevenlabs_voice_id", None)
    )
    if use_elevenlabs:
        try:
            return _synthesize_narration_elevenlabs(script, elevenlabs_api_key, primary_variant.elevenlabs_voice_id), None
        except Exception:
            logger.warning("ElevenLabs narration failed — falling back to on-worker Chatterbox synthesis", exc_info=True)

    return None, dialogue


_DEFAULT_SHOT_DURATION_SECONDS = 3
# Per-job client-side polling deadline for a multi-shot generation — scales
# with shot count since the worker now runs N sequential LTX generations
# (plus Chatterbox load/synthesis, concat, and mux) inside ONE job rather
# than this backend submitting N separate jobs (see module docstring on
# why: keeping the model resident across shots in one job is both faster
# and more reliable than N independent cold-ish RunPod round trips). Not
# yet tuned against real multi-shot timing — 400s/shot is a conservative
# starting estimate, adjust once real per-shot generation time is observed
# live on a multi-shot script.
_MULTI_SHOT_TIMEOUT_FLOOR_SECONDS = 1200
_MULTI_SHOT_TIMEOUT_PER_SHOT_SECONDS = 400

# How many shots may chain off each other before forcing a re-anchor on a
# real character portrait. Each chained shot generates from the previous
# shot's final frame, so quality drift and any artifact compound with every
# hop; re-anchoring periodically resets that against a known-good photo.
# Untuned starting value — the tradeoff is continuity (higher) vs identity
# fidelity and drift (lower), and only real output can settle it.
_MAX_CHAINED_SHOTS = 3

_REFERENCE_IMAGE_MAX_DIMENSION = 768
_REFERENCE_IMAGE_JPEG_QUALITY = 88


def _downscale_reference_image(raw: bytes) -> bytes:
    """Re-encodes a character reference photo as a smaller JPEG before it
    goes into the Serverless request body — see the docstring on
    _reference_bytes_for's caller for why: this is only used to anchor
    LTX's first frame, not shown to end users, so trading resolution for
    request-body size is free. Falls back to the original bytes if
    Pillow can't decode them (lets the existing "bad image, falls back to
    text-to-video" path downstream handle it rather than failing here)."""
    from io import BytesIO
    from PIL import Image

    try:
        img = Image.open(BytesIO(raw))
        img = img.convert("RGB")
        w, h = img.size
        longest = max(w, h)
        if longest > _REFERENCE_IMAGE_MAX_DIMENSION:
            scale = _REFERENCE_IMAGE_MAX_DIMENSION / longest
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))))
        out = BytesIO()
        img.save(out, format="JPEG", quality=_REFERENCE_IMAGE_JPEG_QUALITY)
        return out.getvalue()
    except Exception:
        logger.warning("Failed to downscale reference image — sending original bytes", exc_info=True)
        return raw


def generate_toon_video_selfhosted(script, variants: list, endpoint_id: str,
                                    duration_seconds: Optional[float] = None,
                                    use_allocation_retry: bool = False,
                                    background=None,
                                    elevenlabs_api_key: Optional[str] = None) -> bytes:
    """Returns raw video bytes for the caller to persist via
    app.media.storage.upload(). Raises SelfHostedVideoGenerationError (cast
    not ready, or a script with no shots at all) or whatever
    app.media.runpod_serverless_client/ltx_workflow raise on a
    Serverless-side failure.

    Builds one LTX generation PER SHOT (see module docstring) — each shot
    resolves its own speaker's identity/LoRA via _resolve_shot_variant and
    gets its own prompt via _build_shot_prompt, so shot_type/camera_movement
    drive a real distinct camera cut instead of shared descriptive text
    within one continuous clip. The worker (deploy/runpod_serverless/
    handler.py) receives the whole ordered list and does the actual
    per-shot submission/concat/mux itself in one job.

    use_allocation_retry: set by the batch runner for only the first job of
    a scheduled window (app/services/culturetoon_selfhosted_batch.py) —
    routes through run_inference_job_with_allocation_retry instead of the
    plain call, since a cold Serverless endpoint failing to allocate a
    worker is a distinct failure mode from an individual clip's own
    generation failing.

    duration_seconds: an optional CAP on total included runtime, NOT a
    per-clip override anymore — each shot uses its own authored
    duration_seconds field (falling back to _DEFAULT_SHOT_DURATION_SECONDS
    when a shot is missing one). Shots are included in script order until
    adding the next one would exceed this cap (always includes at least
    the first shot); omit it to generate every shot in the script.
    Existing callers compute this as the script's own total duration, so
    in practice this almost always includes every shot — the cap mainly
    exists for a caller that deliberately wants a shorter/quicker test
    render, the same use this parameter served before per-shot generation.

    background: the resolved ToonBackground for this script (see
    _build_shot_prompt) — this function doesn't resolve it itself (no DB
    session assumption here, callers already have one), so a caller that
    wants Location context in the prompt must fetch and pass it
    explicitly. Repeated on EVERY shot's own prompt now, since each shot
    is an independent generation that needs its own scene-setting context
    (previously prepended once for the single continuous clip).

    elevenlabs_api_key: the primary cast member's brand's own decrypted
    ElevenLabs key, when voice_provider="elevenlabs" — this function
    doesn't resolve or decrypt it itself (same no-DB-session reasoning as
    background above), so a caller that wants ElevenLabs narration instead
    of the default on-worker Chatterbox synthesis must fetch and decrypt
    it explicitly (see generate_video_for_toon_selfhosted and
    culturetoon_selfhosted_batch.py for the two existing examples, both
    mirroring app/services/culturetoon_video.py's identical
    decrypt-and-pass pattern)."""
    import httpx
    from app.media import ltx_workflow, runpod_serverless_client

    resolve_ready_lora(variants)  # fail fast if any cast member isn't LoRA-ready

    shots = script.shots or []
    if not shots:
        raise SelfHostedVideoGenerationError("Script has no shot data — nothing to generate")

    reference_image_cache: dict = {}

    def _reference_bytes_for(variant) -> Optional[bytes]:
        # Cached per variant id — real scripts reuse the same speaker
        # across multiple shots (e.g. Hans in 6 of his own 9 shots), no
        # need to re-fetch the same photo once per shot. Each cast member's
        # photo is still embedded once PER SHOT they speak in (the worker's
        # shot_reference_images_base64 contract is positional, one entry
        # per shot_workflows entry — see handler.py's _generate_single_shot
        # loop), so a multi-shot script re-sends the same bytes multiple
        # times. Confirmed live 2026-08-31: an unmodified 1024x1024 PNG
        # (~1.3MB) repeated across a 9-shot/3-character script pushed the
        # combined base64 payload past RunPod Serverless's 10MiB /run body
        # cap ("exceeded max body size of 10MiB", no useful detail on the
        # generic 400 until the response body itself was inspected). Since
        # this is only ever used to anchor LTX's first frame (not shown to
        # end users at full res), downscaling + re-encoding as JPEG here
        # cuts each image from ~1.3MB to ~70KB — about 18x — with no
        # worker-side change needed, since the worker just base64-decodes
        # whatever bytes it's given and hands them to ComfyUI's
        # content-sniffing upload endpoint regardless of the literal
        # "reference.png" filename it's uploaded under.
        if variant is None:
            return None
        key = str(variant.id)
        if key not in reference_image_cache:
            image_url = getattr(variant, "image_url", None)
            if not image_url:
                reference_image_cache[key] = None
            else:
                try:
                    raw = httpx.get(image_url, timeout=30).content
                    reference_image_cache[key] = _downscale_reference_image(raw)
                except Exception:
                    logger.warning(
                        "Failed to fetch reference image for %s — that shot falls back to text-to-video",
                        getattr(variant, "name", key), exc_info=True,
                    )
                    reference_image_cache[key] = None
        return reference_image_cache[key]

    shot_workflows = []
    shot_reference_images = []
    shot_chain_from_previous = []
    chained_run = 0
    cumulative_duration = 0.0
    for shot in shots:
        shot_duration = shot.get("duration_seconds") or _DEFAULT_SHOT_DURATION_SECONDS
        if duration_seconds is not None and shot_workflows and cumulative_duration + shot_duration > duration_seconds:
            break  # cap reached — always include at least the first shot

        shot_variant = _resolve_shot_variant(shot, variants)
        shot_prompt = _build_shot_prompt(shot, background=background) or "A character reacts to their day."
        reference_bytes = _reference_bytes_for(shot_variant)

        # Explicit random seed per shot — confirmed live 2026-08-28: with
        # no seed passed, build_workflow() leaves the template's hardcoded
        # seed=0 in place, so any two calls with identical prompt/duration/
        # lora (e.g. retrying the same Toon) produce byte-identical
        # ComfyUI inputs, which hits ComfyUI's own execution cache and
        # returns an empty `outputs` dict despite status_str="success".
        workflow = ltx_workflow.build_workflow(
            shot_prompt, shot_duration,
            lora_path=getattr(shot_variant, "lora_path", None),
            seed=random.randint(1, 2**31 - 1),
            # Confirmed live 2026-08-29/30: pure text-to-video with only a
            # character LoRA for identity produced 2-3 held poses, not
            # continuous animation — image-to-video, anchoring the first
            # frame on the shot's own speaker's real photo, is LTX's own
            # documented pattern for grounding identity while leaving the
            # base model free to generate real motion. Best-effort: a
            # shot whose photo can't be fetched falls back to text-to-video
            # rather than failing the whole multi-shot generation.
            reference_image_filename="reference.png" if reference_bytes else None,
        )
        shot_workflows.append(workflow)
        shot_reference_images.append(reference_bytes)
        # Continuity: chain this shot off the PREVIOUS shot's last frame
        # (worker-side, see handler.py) instead of re-anchoring on the
        # speaker's solo portrait, so consecutive shots share a scene,
        # lighting and character positions — and can show more than one
        # character at once, which a solo portrait anchor structurally
        # cannot. Re-anchors on the portrait when:
        #   - it's the first shot (nothing to chain from), or
        #   - the shot marks a scene change, or
        #   - _MAX_CHAINED_SHOTS have already been chained in a row, which
        #     bounds the drift/artifact propagation an unbroken chain
        #     accumulates (each hop generates from the last one's output).
        is_scene_change = bool(shot.get("scene_change") or shot.get("is_scene_change"))
        chain = bool(shot_workflows[:-1]) and not is_scene_change and chained_run < _MAX_CHAINED_SHOTS
        shot_chain_from_previous.append(chain)
        chained_run = chained_run + 1 if chain else 0
        cumulative_duration += shot_duration

    narration_audio_bytes, narration_text = _resolve_narration(script, variants, elevenlabs_api_key=elevenlabs_api_key)

    timeout_seconds = max(
        _MULTI_SHOT_TIMEOUT_FLOOR_SECONDS,
        300 + len(shot_workflows) * _MULTI_SHOT_TIMEOUT_PER_SHOT_SECONDS,
    )

    call = (
        runpod_serverless_client.run_inference_job_with_allocation_retry
        if use_allocation_retry else runpod_serverless_client.run_inference_job
    )
    return call(
        endpoint_id,
        shot_workflows=shot_workflows, shot_reference_images=shot_reference_images,
        shot_chain_from_previous=shot_chain_from_previous,
        narration_audio_bytes=narration_audio_bytes, narration_text=narration_text,
        timeout_seconds=timeout_seconds,
    )



# ── LTX-2.5 ────────────────────────────────────────────────────────────────

def use_ltx25() -> bool:
    """Whether the self-hosted path should render via LTX-2.5.

    Opt-in by env var rather than a hard switch: the 2.3 path below is the
    one that has been running in production, and flipping the default
    silently would swap the renderer for every brand at once. Set
    LTX_MODEL_VERSION=2.5 to enable.
    """
    return (os.getenv("LTX_MODEL_VERSION", "") or "").strip() == "2.5"


def build_ltx25_scene_prompt(script, variants: list, background=None, shots: Optional[list] = None,
                              continuation_anchor: bool = False) -> str:
    """One prompt describing a SEGMENT of the scene, cast included.

    2.5 renders a multi-shot scene in a single generation (native
    multishot), so unlike the 2.3 path this does not produce one prompt per
    shot — cuts are expressed inside the text instead. A "segment" is a
    run of consecutive shots rendered as one generation — see
    _split_shots_into_segments's docstring for why the whole script isn't
    always one segment.

    shots, when given, overrides getattr(script, "shots", ...) — the
    caller passes just this segment's own shots (their own "shot_number"
    is preserved, so cut labels stay globally correct even mid-script).

    continuation_anchor is True for every segment after the first: its
    reference image is the PREVIOUS segment's actual last rendered frame,
    not the composite portrait grid, so the framing/instructions around
    "the opening frame" change to match what's really being conditioned on.

    Character descriptions come from the parent Character row, never
    invented. Confirmed the hard way 2026-09-02: a hand-written prompt
    called Wen a woman when characters.description says "A Chinese man",
    and because 2.5 denoises audio jointly with video that produced a
    female VOICE too. On 2.3 that was impossible, since narration came from
    a separately chosen TTS voice — so getting this from the database is no
    longer cosmetic.
    """
    positions = ["LEFT", "CENTRE", "RIGHT", "FAR RIGHT", "BACKGROUND"]
    parts = []

    # Identity comes FIRST, before setting or premise, and is explicitly tied
    # to the reference image rather than left implicit. This is a first-frame
    # image-conditioned model with no per-character LoRA, so the ONLY thing
    # binding a name to a face is this text agreeing with the composite
    # anchor's left-to-right order — putting it up front, ahead of anything
    # else the model has to hold in mind, is what a user asked for directly
    # (2026-09-02) after a render confused which face was which.
    # A single variant means this segment anchors on ONE character's own
    # plain portrait (see generate_toon_video_ltx25) — there is no grid, so
    # LEFT/CENTRE/RIGHT positions would be meaningless and actively
    # confusing ("LEFT is Hans" when the reference image is just Hans,
    # full-frame). Position language only applies when there's actually a
    # multi-portrait composite to describe positions within.
    single_anchor = len(variants) == 1
    described = []
    voice_lines = []
    position_of = {}
    for index, variant in enumerate(variants):
        position = positions[index] if index < len(positions) else f"POSITION {index + 1}"
        # Recorded for every cast member, even one with no description, so
        # per-shot speaker attribution below can still place them.
        position_of[str(getattr(variant, "id", ""))] = (getattr(variant, "name", "") or "", "" if single_anchor else position)
        name = (getattr(variant, "name", "") or "").strip()
        character = getattr(variant, "character", None)
        text = (getattr(character, "description", None) or "").strip()
        if text:
            if single_anchor:
                described.append(f"{name}: {text}" if name else text)
            else:
                described.append(f"{position} is {name}: {text}" if name else f"{position}: {text}")

        # Audio is denoised JOINTLY with video on 2.5 (see module docstring), so a
        # character's voice is as much an identity trait as their face — but until
        # 2026-09-02 this prompt only ever said what each character LOOKS like,
        # never how they should SOUND, leaving accent/vocal tone to be guessed
        # from appearance alone on a model already prone to mixing identities up
        # (confirmed live: a German character's line rendered in an Indian accent).
        # CharacterVariant.voice_description (added 2026-09-03) is a dedicated,
        # user-editable field for exactly this — visible in the character editor
        # so a wrong accent can be fixed directly instead of by rewriting the
        # whole appearance description. Falls back to the appearance text (still
        # somewhat useful — "Indian expat", "German middle aged man" — but never
        # written with voice in mind) only when the user hasn't set one.
        voice_text = (getattr(variant, "voice_description", None) or "").strip()
        if not voice_text and text:
            voice_text = f"accent, vocal tone and speech pattern fitting being {text}"
        if voice_text:
            if single_anchor:
                voice_lines.append(f"{name}'s voice: {voice_text}" if name else f"Voice: {voice_text}")
            else:
                voice_lines.append(
                    f"{position} ({name})'s voice: {voice_text}" if name else f"{position}'s voice: {voice_text}"
                )
    if described or voice_lines:
        if continuation_anchor:
            who = "the same person" if single_anchor else f"same {len(variants)} real individuals"
            parts.append(
                f"This is a direct continuation of the same scene, {who}, same location — the "
                "reference image is the actual last frame of what just happened, not a new "
                "opening. For identity only (not blocking):"
            )
        elif single_anchor:
            parts.append(
                "The reference image is a face anchor for exactly one real person — use it ONLY "
                "to know what they look like, never as a pose or blocking to hold. Any other "
                "people appearing in the shots below are NOT this reference image and have no "
                "face anchor of their own — render them as ordinary, unremarkable background "
                "people, distinct from the one anchored identity below:"
            )
        else:
            parts.append(
                f"The reference image is a face anchor for exactly {len(variants)} real "
                "individuals, arranged left to right in this exact order — use it ONLY to know "
                "what each of them looks like, never as the scene's blocking or starting pose:"
            )
        parts.extend(described)
        parts.append(
            "Voice is part of each character's fixed identity, exactly like their face — it "
            "must match THEIR OWN description, not another character's, and never drift "
            "mid-video:"
        )
        parts.extend(voice_lines)

    # The script's OWN world comes next. An AI script now generates a
    # `setting` grounded in the trend's subject (stored on scene_direction),
    # so a Minecraft trend is staged inside a Minecraft world rather than in
    # a neutral room where people discuss Minecraft. Before this existed, a
    # script carried no setting at all and a toon with no Location selected
    # reached the model with nothing describing the place — which is what
    # produced bland, non-cinematic backgrounds.
    #
    # A chosen Location still wins when present: it is an explicit user
    # decision and has its own art direction.
    scene_setting = (getattr(script, "scene_direction", None) or "").strip()
    if scene_setting and background is None:
        parts.append(f"Setting: {scene_setting}")

    if background is not None:
        name = (getattr(background, "name", None) or "").strip()
        description = (getattr(background, "description", None) or "").strip()
        country = (getattr(background, "country", None) or "").strip()
        if name:
            parts.append(f"Setting: {name}" + (f", in {country}" if country else "") + ".")
        if description:
            parts.append(description)
        visual_style = (getattr(background, "visual_style", None) or "").strip()
        if visual_style:
            parts.append(_expand_visual_style(visual_style))

    hook = (getattr(script, "hook_line", None) or "").strip()
    if hook and not continuation_anchor:
        parts.append(f"Premise: {hook}")

    # Tracks the previous shot's "location" so a repeat (same place) stays
    # silent and a change gets an explicit cut cue — see culturetoon_script.py's
    # "location" field docs. Without this, the ONE global Setting/background
    # above is the only place description the model ever sees, so a script
    # whose shots are meant to move somewhere else has no signal to actually
    # do that inside this single continuous generation. Confirmed live
    # 2026-09-02: a three-country script stayed on one background for the
    # whole video because nothing ever told the model to cut anywhere.
    previous_location = None
    segment_shots = shots if shots is not None else (getattr(script, "shots", None) or [])
    for index, shot in enumerate(segment_shots, start=1):
        shot_text = _build_shot_prompt(shot, background=None)
        if not shot_text:
            continue
        # shot_number is the GLOBAL position in the full script (preserved even
        # when `shots` is one segment out of several), so cut labels stay
        # meaningful mid-script instead of resetting to "SHOT 1" every segment.
        global_number = shot.get("shot_number", index)
        lead = "SHOT 1" if (index == 1 and not continuation_anchor) else f"CUT TO SHOT {global_number}"

        location = (shot.get("location") or "").strip()
        location_cue = ""
        if location and location != previous_location:
            location_cue = f" NEW LOCATION — {location}."
        if location:
            previous_location = location

        # Name WHO speaks, and where they are in frame.
        #
        # _build_shot_prompt emits `saying "..."` with no speaker, which was
        # fine on the 2.3 path: each shot was its own generation anchored on
        # that speaker's photo, so identity was implicit. In this
        # whole-scene prompt there is no per-shot anchoring, so unattributed
        # dialogue leaves the model to guess which of several characters is
        # talking. Confirmed live 2026-09-02: on a three-hander, the shot
        # belonging to the third character was rendered as a DUPLICATE of
        # the second one instead, speaking her line.
        # Only an EXPLICIT speaker names a focus. _resolve_shot_variant falls
        # back to the first-listed cast member for a shot with no
        # speaker_variant_id, which is right for choosing a LoRA on the 2.3
        # path but wrong here: it made a silent ensemble closing shot read as
        # "Zara is the focus", and 2.5 then gave Zara a line. Confirmed live
        # 2026-09-02 — the closing shot belonged to no one and Zara spoke in
        # it. An unattributed shot gets no focus claim at all.
        speaker = _resolve_shot_variant(shot, variants) if shot.get("speaker_variant_id") else None
        speaker_id = str(getattr(speaker, "id", "")) if speaker is not None else ""
        name, position = position_of.get(speaker_id, ("", ""))

        # A subject shot has nobody in it, so naming a focus character would
        # put them back on screen — _build_shot_prompt already says the frame
        # is empty of people, and the voice-over line is attributed there.
        focus_type = (shot.get("shot_focus") or "character").strip().lower()
        if focus_type == "subject":
            parts.append(f"{lead} —{location_cue} {shot_text}")
            continue
        # Audio is denoised JOINTLY with video on 2.5, so silence is something
        # to ask for, not the default. With no line in the prompt and nothing
        # saying the shot is silent, the model invents dialogue and hands it
        # to whoever it thinks the focus is.
        silent = not (shot.get("dialogue") or "").strip()
        silence_note = (
            " No one speaks in this shot — no dialogue, no voice-over, mouths closed, "
            "ambient sound only."
            if silent else ""
        )
        if name:
            who = f"{name} ({position})" if position else name
            focus = f"{who} is the focus of this shot"
            if not silent:
                focus += f" and is the one speaking — the line is {name}'s, not another character's"
            parts.append(f"{lead} —{location_cue} {focus}. {shot_text}{silence_note}")
        else:
            parts.append(f"{lead} —{location_cue} {shot_text}{silence_note}")

    parts.append(
        "Consistent character appearance throughout, faces matching the reference image exactly. "
        "Natural facial performance and lip movement synced to the dialogue."
    )
    if continuation_anchor:
        # The reference image here is a REAL scene frame (the previous segment's
        # last frame), not the artificial portrait grid — so the risk flips: instead
        # of freezing on an unnatural line-up, the model can freeze on whatever pose
        # that last frame happened to catch. Same "keep moving" instruction, different
        # reason.
        parts.append(
            "The reference image is where the scene physically was one instant ago, not a "
            "pose to hold. Keep moving immediately in a way that matches this segment's own "
            "shots below — do not freeze on the reference image's exact pose."
        )
    else:
        # The composite anchor is three (or more) head-and-shoulders portraits evenly spaced
        # side by side — nothing but a face reference. Without an explicit instruction the model
        # reads that even spacing as the scene's actual blocking and holds it: a frozen line-up
        # for the whole video with one character stepping forward per line, confirmed live
        # 2026-09-02 as a rendered "cast standing together for no reason" result. Each shot's own
        # blocking (built above) already says who is actually present in that shot; this tells the
        # model to trust that over the anchor's layout.
        parts.append(
            "The opening frame is a face reference only, not the scene's blocking or a starting pose "
            "to hold. Break from it immediately: from SHOT 1, only the characters named in that "
            "shot's own blocking are on screen, positioned and moving as that blocking describes — "
            "characters not named in a shot are not visible in it. Continuous natural movement "
            "throughout, no frozen held poses, no static line-up of the cast waiting their turn."
        )
    # The opening frame is a composite showing every cast member side by side,
    # so the model has seen each face at a fixed position. When a later shot
    # moves one of them elsewhere in frame, it can leave a COPY behind at the
    # anchor position — confirmed live 2026-09-02, a second Zara sitting in
    # the background. Stating the cast is a closed set of single individuals
    # is the prompt-side counterpart to the negative prompt's duplicate terms.
    cast_names = [n for n, _ in position_of.values() if n]
    if cast_names:
        noun = "individual" if len(cast_names) == 1 else "individuals"
        parts.append(
            f"The anchored cast is exactly {len(cast_names)} {noun}: {', '.join(cast_names)}. "
            "There is exactly ONE of each of them on screen at any time — never two of the same "
            "character in the same frame, never a copy or double of anyone in the background. "
            "The reference image is a reference of who they are, not a fixed seating arrangement."
        )
    return " ".join(p for p in parts if p)


# How long to wait on a 2.5 render, from the thing that actually drives it.
#
# The previous formula was max(1200, 300 + shots * 120) — shot COUNT, a
# leftover from the 2.3 path where every shot was its own generation. Under
# 2.5 the whole scene is ONE generation whose length scales with DURATION, so
# a 37s five-shot video was given 1200s for what needs ~680s of generation
# plus a cold start. Confirmed live 2026-09-02: it timed out at exactly
# 1200s, and because this argument was passed explicitly, raising the
# client's default had no effect on this path at all.
_COLD_START_ALLOWANCE_SECONDS = 900   # image pull + LTX checkpoint load from the volume
_RENDER_VARIANCE = 1.4                # measured 18.2-18.8x, plus headroom for a busy GPU
_MAX_TIMEOUT_SECONDS = 5400


def ltx25_timeout_seconds(duration_seconds) -> int:
    """Wall-clock budget for a whole-scene 2.5 render, including the wait for
    a cold worker — this clock starts at submission, not at generation."""
    from app.services.culturetoon_usage import RENDER_GPU_SECONDS_PER_OUTPUT_SECOND

    generation = float(RENDER_GPU_SECONDS_PER_OUTPUT_SECOND) * (duration_seconds or 0) * _RENDER_VARIANCE
    return int(min(_MAX_TIMEOUT_SECONDS, _COLD_START_ALLOWANCE_SECONDS + generation))


# The official LTX-2.5 template's sampling schedule (ManualSigmas nodes in
# ltx25_image_to_video.api.json) is a FIXED 8 steps (base pass) + 3 steps
# (upscale pass) — Comfy-Org's own tuning for their 5s/121-frame demo.
# build_workflow() never touches those nodes; only duration changes, so a
# longer render spreads the exact same step budget over more frames
# (frames = duration_seconds * 24 + 1). Confirmed live 2026-09-03, frame by
# frame, on a 33s/5-shot/3-character render (793 frames on an 11-step
# schedule): ~5-7s of near-static replay of the portrait anchor before the
# model diverged from it at all, then the whole cast collapsed into one
# face for the rest of the video. 12s (289 frames) is the only duration
# this path has ever been confirmed to hold up at. Rather than raise the
# step count (touches the official template graph, which this codebase's
# own comments already warn against hand-modifying without real testing —
# see ltx25_workflow.py's header), each generation is kept within this
# budget and a longer script is rendered as multiple chained segments
# instead — see _split_shots_into_segments.
LTX25_SEGMENT_TARGET_SECONDS = 15
# A segment may run past the target, up to this hard ceiling, ONLY to avoid
# splitting a shot away from one it's reacting to/interacting with (see
# _is_coupled_shot) — cutting mid-interaction is worse than a slightly long
# segment. Past this, it splits regardless.
LTX25_SEGMENT_HARD_CAP_SECONDS = 20


def _is_coupled_shot(shot: dict) -> bool:
    """True when `shot` must stay glued to the shot immediately before it —
    a reaction to what just happened, not its own fresh beat. A segment
    boundary here would cut the joke/exchange in half: imagine splitting
    right between a line and the shocked reaction to it. Heuristics, since
    "this is a reaction" isn't a stored field:
    - no dialogue at all (a pure reaction/reveal shot has nothing to say on
      its own — it exists only in relation to its neighbor)
    - shot_focus "both" (character + subject together) with NO speaker of
      its own — riding along with whoever is already established, not
      introducing a new voice.

    Does NOT treat EVERY "both" shot as coupled — an earlier version did,
    and that was wrong: confirmed live 2026-09-07 on a solar eclipse
    script, where each stage of the eclipse had its OWN distinct speaker
    (Zara, then Blix, then Captain Nova, then Zara again) with shot_focus
    "both" throughout (character explaining alongside the phenomenon). The
    old rule glued every one of those to whichever speaker got there
    first, so Blix's and the second Zara shot's lines were rendered under
    someone ELSE's anchored face entirely — the exact misattribution bug
    this whole segmentation redesign exists to prevent, just reintroduced
    by an over-broad coupling rule. A "both" shot with its own speaker is a
    real, fresh beat and must be allowed to start its own segment.

    Also does NOT check whether blocking/visual/action merely NAME 2+ cast
    members — an earlier version did, but that fires on completely
    ordinary blocking like "Carlos centre, Hans left" (Hans just present in
    frame, not interacting), which isn't a reaction at all. That mattered
    once _split_shots_into_segments started also cutting on a SPEAKER
    change, not just duration: a real change of speaker should split even
    when the outgoing speaker is still named in the new shot's blocking —
    that's the whole point of anchoring each segment on its own primary."""
    if not (shot.get("dialogue") or "").strip():
        return True
    return (shot.get("shot_focus") or "").strip().lower() == "both" and not shot.get("speaker_variant_id")


def _split_shots_into_segments(shots: list,
                                target_seconds: int = LTX25_SEGMENT_TARGET_SECONDS,
                                hard_cap_seconds: int = LTX25_SEGMENT_HARD_CAP_SECONDS) -> list:
    """Groups consecutive shots into segments safe for one LTX-2.5
    generation each (see LTX25_SEGMENT_TARGET_SECONDS above for why this
    exists at all) AND anchorable on a SINGLE character's own portrait
    rather than the multi-portrait composite.

    Confirmed live 2026-09-03 (docs/culturix-video-pipeline.md section 2):
    the composite anchor itself — not duration, not CFG, not image-
    conditioning strength, all independently tested — is the actual
    ceiling. Two of three composite face-crops stayed frozen in their
    portrait pose for an entire video regardless of any of that tuning.
    A user's suggestion fixes this from a different angle: keep only the
    scene's PRIMARY (speaking) character precisely anchored per segment,
    and accept that any other cast member on screen in that segment (e.g.
    a silent reaction shot) renders as an unanchored background presence
    instead — no face reference to freeze on to in the first place.

    So a shot starts a NEW segment when ANY of:
    - its scene_index differs from the segment's established scene —
      UNCONDITIONALLY, never softened by coupling. A coupled reaction shot
      can stay glued to a different SPEAKER, but not to a different
      BACKDROP: the anchor image bakes one specific scene's backdrop into
      the composite PNG (see build_composite_anchor's own docstring), so a
      shot from scene 1 glued into a scene 0 segment would render against
      the wrong scene's backdrop regardless of who's speaking. Absent
      (None) for a script that never had plan_scenes() run over it — those
      scripts behave exactly as before this existed.
    - it would push the current segment past target_seconds and isn't
      coupled to what's already in it (same rule as before), or
    - its speaker_variant_id differs from the segment's established
      primary speaker — UNLESS it's coupled (see _is_coupled_shot): an
      interaction/reaction beat stays glued to its predecessor's primary
      even if, taken alone, it would "belong" to someone else, exactly
      like keeping a reaction shot attached to the line it's reacting to.
    A shot with no speaker (a pure reaction/subject shot) never changes
    the segment's established primary by itself. Same for scene_index."""
    segments = []
    current: list = []
    current_total = 0
    current_primary = None
    current_scene_index = None
    for shot in shots:
        duration = shot.get("duration_seconds") or 0
        speaker = shot.get("speaker_variant_id")
        scene_index = shot.get("scene_index")
        scene_changed = (
            bool(current) and scene_index is not None
            and current_scene_index is not None and scene_index != current_scene_index
        )
        coupled = bool(current) and _is_coupled_shot(shot)
        primary_changed = bool(current) and bool(speaker) and bool(current_primary) and speaker != current_primary and not coupled
        exceeds_target = bool(current) and (current_total + duration > target_seconds)
        must_split_anyway = exceeds_target and (not coupled or current_total + duration > hard_cap_seconds)
        if current and (scene_changed or primary_changed or must_split_anyway):
            segments.append(current)
            current = [shot]
            current_total = duration
            current_primary = speaker
            current_scene_index = scene_index
            continue
        current.append(shot)
        current_total += duration
        if speaker and not current_primary:
            current_primary = speaker
        if scene_index is not None and current_scene_index is None:
            current_scene_index = scene_index
    if current:
        segments.append(current)
    return segments


def _segment_primary_variant(segment_shots: list, variants: list):
    """The ONE cast member this segment's reference image anchors — the
    first speaker found among its shots, or the first-listed cast member
    if none of them have a speaker at all (e.g. an all-subject segment)."""
    variants_by_id = {str(getattr(v, "id", "")): v for v in variants}
    for shot in segment_shots:
        speaker_id = shot.get("speaker_variant_id")
        if speaker_id and str(speaker_id) in variants_by_id:
            return variants_by_id[str(speaker_id)]
    return variants[0] if variants else None


def _segment_scene_index(segment_shots: list) -> Optional[int]:
    """Which plan_scenes() location this segment's backdrop should be —
    every shot in one segment shares the same scene_index by construction
    (_split_shots_into_segments splits unconditionally on a scene change),
    so the first shot that has one speaks for the whole segment. None for
    a script that never had plan_scenes() run over it, or a segment whose
    shots simply don't carry the field."""
    for shot in segment_shots:
        scene_index = shot.get("scene_index")
        if scene_index is not None:
            return scene_index
    return None


def _segment_is_subject_only(segment_shots: list) -> bool:
    """True when EVERY shot in this segment is shot_focus "subject" — no
    character on screen at all, e.g. a whole segment devoted to explaining
    a solar eclipse with the eclipse itself filling the frame. Such a
    segment must not be anchored on (or chained from) a character's face —
    see generate_toon_video_ltx25's docstring for the live-confirmed
    failure this prevents."""
    return bool(segment_shots) and all(
        (s.get("shot_focus") or "").strip().lower() == "subject" for s in segment_shots
    )


def _extract_last_frame_png(video_bytes: bytes) -> bytes:
    """The still frame at (effectively) the end of `video_bytes`, as PNG —
    used to chain segment N+1's identity conditioning off segment N's
    actual last frame instead of re-anchoring on the static portrait grid
    every ~15s (see generate_toon_video_ltx25). Seeks 0.5s before EOF rather
    than to the exact end, since seeking exactly to a video's duration is
    unreliable across containers/decoders (can land on no frame at all)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        video_path = os.path.join(tmp_dir, "segment.mp4")
        frame_path = os.path.join(tmp_dir, "last_frame.png")
        with open(video_path, "wb") as f:
            f.write(video_bytes)
        result = subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-0.5", "-i", video_path, "-frames:v", "1", "-q:v", "2", frame_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not os.path.exists(frame_path):
            raise SelfHostedVideoGenerationError(
                f"ffmpeg failed extracting the last frame for segment chaining: {result.stderr[-1000:]}"
            )
        with open(frame_path, "rb") as f:
            return f.read()


_SEGMENT_TRANSITION_SECONDS = 0.4


def _probe_duration_seconds(path: str) -> float:
    """ffprobe's own reported duration for one video file — needed to
    compute xfade's cumulative offsets below (each crossfade shortens the
    output timeline by its own length, so every later transition's offset
    has to account for every prior segment AND every prior crossfade)."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SelfHostedVideoGenerationError(
            f"ffprobe failed reading segment duration: {result.stderr[-500:]}"
        )
    return float(result.stdout.strip())


def _concat_video_segments(video_byte_list: list) -> bytes:
    """Joins segment MP4s into one file. A single segment returns as-is —
    nothing to transition between. Multiple segments cross-fade into each
    other (video via xfade, audio via acrossfade) instead of the hard
    `-c copy` cut this used to do — confirmed live 2026-09-08: back-to-back
    segments (each its own independent LTX-2.5 generation — different
    framing/motion/lighting by construction, even mid-scene) read as a
    jarring jump cut with literally no transition. A short, fixed crossfade
    smooths the join without trying to be content-aware about it.
    Re-encoding is unavoidable once frames are actually blended, unlike the
    old stream-copy path."""
    if len(video_byte_list) == 1:
        return video_byte_list[0]

    with tempfile.TemporaryDirectory() as tmp_dir:
        segment_paths = []
        for i, video_bytes in enumerate(video_byte_list):
            path = os.path.join(tmp_dir, f"segment_{i}.mp4")
            with open(path, "wb") as f:
                f.write(video_bytes)
            segment_paths.append(path)

        durations = [_probe_duration_seconds(p) for p in segment_paths]
        # Capped at 40% of the shorter neighbor in any one transition — a
        # crossfade longer than the clip it's fading against is nonsensical,
        # and guards a pathological very-short segment (duration-capped near
        # a script's end) from breaking the filter graph.
        cf = min(
            _SEGMENT_TRANSITION_SECONDS,
            *(min(durations[i], durations[i + 1]) * 0.4 for i in range(len(durations) - 1)),
        )

        video_filters = []
        audio_filters = []
        cumulative = durations[0]
        v_label, a_label = "0:v", "0:a"
        for i in range(1, len(segment_paths)):
            is_last = i == len(segment_paths) - 1
            v_out = "vout" if is_last else f"v{i}"
            a_out = "aout" if is_last else f"a{i}"
            offset = cumulative - cf
            video_filters.append(
                f"[{v_label}][{i}:v]xfade=transition=fade:duration={cf:.3f}:offset={offset:.3f}[{v_out}]"
            )
            audio_filters.append(f"[{a_label}][{i}:a]acrossfade=d={cf:.3f}:c1=tri:c2=tri[{a_out}]")
            v_label, a_label = v_out, a_out
            cumulative += durations[i] - cf

        output_path = os.path.join(tmp_dir, "combined.mp4")
        cmd = ["ffmpeg", "-y"]
        for path in segment_paths:
            cmd += ["-i", path]
        cmd += [
            "-filter_complex", ";".join(video_filters + audio_filters),
            "-map", f"[{v_label}]", "-map", f"[{a_label}]",
            "-c:v", "libx264", "-c:a", "aac",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            raise SelfHostedVideoGenerationError(
                f"ffmpeg failed cross-fading video segments: {result.stderr[-1000:]}"
            )
        with open(output_path, "rb") as f:
            return f.read()


def _fetch_portrait_anchor(variant, backdrop: Optional[bytes]) -> bytes:
    """A single-character reference image — build_composite_anchor with ONE
    image is just that one portrait, full-frame, no panel dividers at all
    (slot_width becomes the whole width). Used per segment now instead of
    the multi-portrait composite — see generate_toon_video_ltx25's own
    docstring for why."""
    import httpx
    from app.media import ltx25_workflow

    image_url = getattr(variant, "image_url", None)
    image_bytes = []
    if image_url:
        try:
            image_bytes = [httpx.get(image_url, timeout=30).content]
        except Exception:
            logger.warning(
                "Could not fetch %s's portrait for this segment's anchor",
                getattr(variant, "name", "?"), exc_info=True,
            )
    return ltx25_workflow.build_composite_anchor(image_bytes, backdrop_bytes=backdrop)


def _scrub_unanchored_names(text: str, anchored_name: str, other_names: list) -> str:
    """Replaces any OTHER cast member's name in `text` with a generic
    reference — a segment can only precisely anchor ONE identity (see
    generate_toon_video_ltx25's own docstring on why), so blocking/action/
    visual text that still names a second or third character produces a
    duplicate of the anchored face or a generic imposter instead of that
    character, not themselves. Confirmed live 2026-09-08 on two separate
    scripts (a wide shot, and a scene's opening AND closing "whole cast
    together" beat) despite the script-writer prompt explicitly forbidding
    this — a text instruction to the WRITER has proven unreliable twice
    now, so this enforces it deterministically at the last point before
    the render actually sees the text, rather than trying a third,
    stronger-worded prompt fix."""
    if not text:
        return text
    scrubbed = text
    for name in other_names:
        name = (name or "").strip()
        if not name or name.lower() == (anchored_name or "").strip().lower():
            continue
        scrubbed = re.sub(r"\b" + re.escape(name) + r"\b", "another figure nearby", scrubbed, flags=re.IGNORECASE)
    return scrubbed


def _sanitize_segment_shots(segment_shots: list, primary_variant, all_variants: list) -> list:
    """A COPY of segment_shots with every OTHER cast member's name scrubbed
    out of blocking/action/visual text (see _scrub_unanchored_names) —
    dialogue is untouched, since that's always the segment's own anchored
    speaker's line. The segment's own primary's name is left alone.
    Returns segment_shots unchanged (same list, no copy) when there's only
    one cast member total — nothing to scrub."""
    if len(all_variants) < 2:
        return segment_shots
    anchored_name = (getattr(primary_variant, "name", "") or "").strip()
    other_names = [
        (getattr(v, "name", "") or "").strip()
        for v in all_variants
        if str(getattr(v, "id", "")) != str(getattr(primary_variant, "id", "")) and getattr(v, "name", None)
    ]
    if not other_names:
        return segment_shots
    sanitized = []
    for shot in segment_shots:
        shot = dict(shot)
        for field in ("blocking", "action", "visual"):
            if shot.get(field):
                shot[field] = _scrub_unanchored_names(shot[field], anchored_name, other_names)
        sanitized.append(shot)
    return sanitized


def generate_toon_video_ltx25(script, variants: list, endpoint_id: str,
                              duration_seconds: Optional[int] = None,
                              background=None, scene_backgrounds: Optional[dict] = None,
                              stats: Optional[dict] = None) -> bytes:
    """Renders a script as one or more LTX-2.5 generations — one per SEGMENT
    (see _split_shots_into_segments) — concatenated into a single file.

    Each segment anchors on a SINGLE character's own portrait — the
    segment's primary (speaking) cast member — not the multi-portrait
    composite. A user's suggestion, 2026-09-03, after the composite anchor
    itself was confirmed as the actual ceiling (docs/culturix-video-
    pipeline.md section 2: two of three composite face-crops stayed frozen
    for an entire video, independent of duration, CFG, or image-strength
    tuning — all separately tested and all ruled out). Any other cast
    member visible in a segment (e.g. a silent reaction shot with two
    people on screen) renders as an unanchored background presence instead
    — the tradeoff this approach deliberately accepts: exactly one
    precisely-identity-matched person per segment, everyone else generic.

    When consecutive segments share the same primary AND the same scene
    (a duration-forced split mid-speaker, not a change of who's talking or
    where), the later one chains off the earlier one's own last rendered
    frame instead of re-anchoring on a fresh portrait — continuity within
    one person's own coverage. When the primary changes, OR the scene
    changes (a different planned location's backdrop), that's a real cut,
    so it re-anchors fresh rather than chaining off a frame that doesn't
    show the right face, or the right place, at all.

    background: the script's single DEFAULT backdrop (a ToonBackground-like
    object, or anything with .image_url) — used for every segment on a
    script that was never run through plan_scenes() (no shot carries a
    scene_index), same as before this parameter's sibling existed.
    scene_backgrounds: {scene_index (int): ToonBackground-like object},
    resolved by the caller (this function has no DB session — same
    no-DB-access reasoning as `background` above) from ToonScript.
    scene_backgrounds. Added 2026-09-08 for the theme-driven multi-scene
    rework — a script planned across N locations gets N distinct backdrop
    images instead of one repeated across the whole video. A segment whose
    shots carry no scene_index (or whose scene_index has no matching entry
    here) falls back to `background`, so a partially-migrated or manually-
    edited script still renders sensibly.
    """
    from app.media import ltx25_workflow, runpod_serverless_client
    import httpx

    shots = getattr(script, "shots", None) or []
    if not shots:
        raise SelfHostedVideoGenerationError("Script has no shot data — nothing to generate")

    segments = _split_shots_into_segments(shots)
    primary_variants = [_segment_primary_variant(seg, variants) for seg in segments]
    segment_scene_indices = [_segment_scene_index(seg) for seg in segments]

    # The Location's own art, behind the cast, in the video's first frame.
    # Without it the anchor's backdrop is a flat neutral — better than the
    # portrait's own white studio, but a real backdrop puts the opening shot
    # in the scene instead of leaving the model to establish it after frame 1.
    # Fetched lazily and cached per scene_index — a script with 3 planned
    # scenes needs at most 3 fetches total, not one per segment.
    default_backdrop_url = getattr(background, "image_url", None) if background is not None else None
    backdrop_cache: dict = {}

    def _resolve_backdrop(scene_index: Optional[int]) -> Optional[bytes]:
        bg = (scene_backgrounds or {}).get(scene_index) if scene_index is not None else None
        url = getattr(bg, "image_url", None) if bg is not None else default_backdrop_url
        cache_key = scene_index if bg is not None else "__default__"
        if cache_key not in backdrop_cache:
            fetched = None
            if url:
                try:
                    fetched = httpx.get(url, timeout=30).content
                except Exception:
                    logger.warning("Could not fetch the scene %s backdrop for the anchor", scene_index, exc_info=True)
            backdrop_cache[cache_key] = fetched
        return backdrop_cache[cache_key]

    logger.info("LTX-2.5 generation: %d shots split into %d segment(s), primaries: %s, scenes: %s",
                len(shots), len(segments), [getattr(v, "name", "?") for v in primary_variants],
                segment_scene_indices)

    segment_videos = []
    current_anchor = None
    previous_primary_id = None
    previous_scene_index = None
    for seg_index, segment_shots in enumerate(segments):
        this_scene_index = segment_scene_indices[seg_index]
        backdrop = _resolve_backdrop(this_scene_index)
        # A segment entirely of shot_focus "subject" has nobody on screen by
        # design (e.g. a whole beat explaining a solar eclipse with the
        # eclipse itself filling the frame) — it must never be anchored on,
        # or chained from, a character's face. See _segment_is_subject_only
        # and build_backdrop_only_anchor's own docstrings for the live-
        # confirmed failure this branch exists to prevent.
        subject_only = _segment_is_subject_only(segment_shots)
        if subject_only:
            current_anchor = ltx25_workflow.build_backdrop_only_anchor(backdrop)
            prompt = build_ltx25_scene_prompt(
                script, [], background=background, shots=segment_shots,
                continuation_anchor=False,
            )
            # Whatever comes after this must also re-anchor fresh — chaining
            # a character segment off a face-less subject frame would lose
            # identity just as badly as the bug this branch fixes.
            previous_primary_id = None
            previous_scene_index = None
        else:
            primary_variant = primary_variants[seg_index]
            primary_id = str(getattr(primary_variant, "id", ""))
            is_cut = (
                current_anchor is None
                or primary_id != previous_primary_id
                or this_scene_index != previous_scene_index
            )
            if is_cut:
                current_anchor = _fetch_portrait_anchor(primary_variant, backdrop)
            # Deterministic backstop for a script that still named 2+ cast
            # members in one shot's blocking/action/visual despite the
            # writer prompt forbidding it — see _sanitize_segment_shots'
            # own docstring.
            sanitized_shots = _sanitize_segment_shots(segment_shots, primary_variant, variants)
            prompt = build_ltx25_scene_prompt(
                script, [primary_variant], background=background, shots=sanitized_shots,
                continuation_anchor=not is_cut,
            )
            previous_primary_id = primary_id
            previous_scene_index = this_scene_index

        segment_duration = sum(s.get("duration_seconds", 0) for s in segment_shots) or 5
        workflow = ltx25_workflow.build_workflow(prompt, segment_duration)
        segment_stats: dict = {}
        video_bytes = runpod_serverless_client.run_inference_job(
            endpoint_id, workflow, reference_image_bytes=current_anchor,
            timeout_seconds=ltx25_timeout_seconds(segment_duration),
            stats=segment_stats,
        )
        segment_videos.append(video_bytes)
        if stats is not None:
            # Summed across segments — record_usage's cost calculation reads
            # this expecting ONE number for the whole render, not per-segment.
            stats["execution_seconds"] = (stats.get("execution_seconds") or 0) + (segment_stats.get("execution_seconds") or 0)
            stats["delay_seconds"] = (stats.get("delay_seconds") or 0) + (segment_stats.get("delay_seconds") or 0)
            stats.setdefault("worker_ids", []).append(segment_stats.get("worker_id"))
        if seg_index < len(segments) - 1 and not subject_only:
            # Tentative — overwritten by a fresh anchor at the top of the
            # next iteration if that segment's primary or scene turns out to
            # differ (or is itself subject-only). Skipped entirely after a
            # subject-only segment, since that case is ALWAYS overwritten
            # (previous_primary_id/previous_scene_index were just forced to
            # None above).
            current_anchor = _extract_last_frame_png(video_bytes)

    return segment_videos[0] if len(segment_videos) == 1 else _concat_video_segments(segment_videos)

def resolve_scene_backgrounds(session, script) -> Optional[dict]:
    """{scene_index (int): ToonBackground row} for a script planned across
    more than one location — see generate_toon_video_ltx25's own docstring
    on the param this feeds. Shared by both LTX-2.5 callers (the
    interactive generate_video_for_toon_selfhosted below, and the scheduled
    batch runner in culturetoon_selfhosted_batch.py) rather than duplicated,
    since both need the exact same resolution. None for a script with no
    scene_backgrounds at all (predates scene planning, or plan_scenes()
    itself failed when the script was created — both already fail open to
    the script's single `background_id` upstream)."""
    from app.models.toon_background import ToonBackground

    if not getattr(script, "scene_backgrounds", None):
        return None
    scene_bg_ids = {
        entry["scene_index"]: entry["background_id"]
        for entry in script.scene_backgrounds if entry.get("background_id")
    }
    if not scene_bg_ids:
        return None
    rows = session.query(ToonBackground).filter(
        ToonBackground.id.in_([_uuid.UUID(v) for v in scene_bg_ids.values()])
    ).all()
    rows_by_id = {str(r.id): r for r in rows}
    return {
        scene_index: rows_by_id[bg_id]
        for scene_index, bg_id in scene_bg_ids.items() if bg_id in rows_by_id
    } or None


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
    from app.services.culturetoon_usage import (
        record_usage, estimate_selfhosted_video_cost, measured_selfhosted_video_cost,
    )
    from app.social.crypto import decrypt
    import os

    session = SessionLocal()
    toon = None
    duration = 0
    # Populated by the LTX-2.5 path with RunPod's reported executionTime, so
    # usage records a MEASURED cost rather than one derived from the video's
    # duration — RunPod bills compute time, and the two differ by more than
    # an order of magnitude (a 12s video costs ~226s of GPU).
    run_stats: dict = {}
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

        # One distinct backdrop per plan_scenes() location, for a script
        # that was planned across more than one — see resolve_scene_
        # backgrounds' and generate_toon_video_ltx25's own docstrings.
        scene_backgrounds = resolve_scene_backgrounds(session, script)

        # Same resolve-and-decrypt pattern as app/services/
        # culturetoon_video.py::generate_video_for_toon: the primary cast
        # member drives voice_provider for the whole video, and a missing/
        # absent brand key fails open to the default on-worker Chatterbox
        # synthesis (see _resolve_narration) rather than blocking
        # generation.
        elevenlabs_api_key = None
        if variants and variants[0].voice_provider == "elevenlabs":
            brand = session.query(CharacterBrand).filter_by(id=toon.brand_id).first()
            if brand and brand.elevenlabs_api_key_encrypted:
                elevenlabs_api_key = decrypt(brand.elevenlabs_api_key_encrypted)

        # LTX-2.5 renders the whole scene in one generation with native
        # synchronized audio and no LoRA, so it skips the per-shot loop,
        # the Chatterbox/ElevenLabs narration path and last-frame chaining
        # entirely — those exist to approximate what 2.5 does itself.
        if use_ltx25():
            video_bytes = generate_toon_video_ltx25(
                script, variants, endpoint_id, duration_seconds=duration, background=background,
                scene_backgrounds=scene_backgrounds, stats=run_stats,
            )
        else:
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
                    output_units=int(duration),
                    cost_usd=(
                        measured_selfhosted_video_cost(run_stats["execution_seconds"])
                        if run_stats.get("execution_seconds") is not None
                        else estimate_selfhosted_video_cost(duration)
                    ),
                )

            # Best-effort, and deliberately so. This runs in `finally`, where
            # a raised exception REPLACES whatever is already propagating —
            # so a failure here both masks the real generation outcome and
            # turns an already-uploaded, already-committed video into a
            # raised error. Seen live 2026-09-02: a render completed and
            # saved, then this raised and the call reported failure.
            # Cost tracking is worth a loud log, never the result.
            try:
                _resilient_commit(session, _apply_usage)
            except Exception:
                logger.exception(
                    "Could not record usage for toon %s — the generation result itself is "
                    "unaffected, but this render is missing from cost tracking", toon_id,
                )
        session.close()
