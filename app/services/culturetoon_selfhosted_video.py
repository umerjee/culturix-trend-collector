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


def build_ltx25_scene_prompt(script, variants: list, background=None) -> str:
    """One prompt describing the WHOLE scene, cast included.

    2.5 renders a multi-shot scene in a single generation (native
    multishot), so unlike the 2.3 path this does not produce one prompt per
    shot — cuts are expressed inside the text instead.

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

    # The script's OWN world comes first. An AI script now generates a
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

    described = []
    position_of = {}
    for index, variant in enumerate(variants):
        position = positions[index] if index < len(positions) else f"POSITION {index + 1}"
        # Recorded for every cast member, even one with no description, so
        # per-shot speaker attribution below can still place them.
        position_of[str(getattr(variant, "id", ""))] = (getattr(variant, "name", "") or "", position)
        character = getattr(variant, "character", None)
        text = (getattr(character, "description", None) or "").strip()
        if not text:
            continue
        name = (getattr(variant, "name", "") or "").strip()
        described.append(f"{position} is {name}: {text}" if name else f"{position}: {text}")
    if described:
        parts.append(f"{len(described)} characters share the scene.")
        parts.extend(described)

    hook = (getattr(script, "hook_line", None) or "").strip()
    if hook:
        parts.append(f"Premise: {hook}")

    for index, shot in enumerate(getattr(script, "shots", None) or [], start=1):
        shot_text = _build_shot_prompt(shot, background=None)
        if not shot_text:
            continue
        lead = "SHOT 1" if index == 1 else f"CUT TO SHOT {index}"

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
        speaker = _resolve_shot_variant(shot, variants)
        speaker_id = str(getattr(speaker, "id", "")) if speaker is not None else ""
        name, position = position_of.get(speaker_id, ("", ""))
        if name:
            who = f"{name} ({position})" if position else name
            focus = f"{who} is the focus of this shot"
            if shot.get("dialogue"):
                focus += f" and is the one speaking — the line is {name}'s, not another character's"
            parts.append(f"{lead} — {focus}. {shot_text}")
        else:
            parts.append(f"{lead} — {shot_text}")

    parts.append(
        "Consistent character appearance throughout, faces matching the opening frame exactly. "
        "Natural facial performance and lip movement synced to the dialogue."
    )
    return " ".join(p for p in parts if p)


def generate_toon_video_ltx25(script, variants: list, endpoint_id: str,
                              duration_seconds: Optional[int] = None,
                              background=None, stats: Optional[dict] = None) -> bytes:
    """Renders a whole script as ONE LTX-2.5 generation.

    No per-shot loop, no LoRA, no narration mux and no last-frame chaining:
    2.5 handles multishot and synchronized audio natively, and identity
    comes from a composite first-frame anchor built from the cast's real
    portraits. Every one of those workarounds existed to approximate
    something 2.5 does itself.
    """
    import httpx
    from app.media import ltx25_workflow, runpod_serverless_client

    shots = getattr(script, "shots", None) or []
    if not shots:
        raise SelfHostedVideoGenerationError("Script has no shot data — nothing to generate")

    total_duration = duration_seconds or getattr(script, "total_duration_seconds", None) or sum(
        s.get("duration_seconds", 0) for s in shots
    ) or 8

    anchor_images = []
    for variant in variants:
        image_url = getattr(variant, "image_url", None)
        if not image_url:
            continue
        try:
            anchor_images.append(httpx.get(image_url, timeout=30).content)
        except Exception:
            logger.warning(
                "Could not fetch %s's portrait for the composite anchor — that identity will "
                "not be anchored", getattr(variant, "name", "?"), exc_info=True,
            )
    anchor = ltx25_workflow.build_composite_anchor(anchor_images)

    prompt = build_ltx25_scene_prompt(script, variants, background=background)
    workflow = ltx25_workflow.build_workflow(prompt, total_duration)
    logger.info("LTX-2.5 generation: %ds, %d shots, %d anchored characters",
                total_duration, len(shots), len(anchor_images))

    return runpod_serverless_client.run_inference_job(
        endpoint_id, workflow, reference_image_bytes=anchor,
        timeout_seconds=max(_MULTI_SHOT_TIMEOUT_FLOOR_SECONDS, 300 + len(shots) * 120),
        stats=stats,
    )

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
                stats=run_stats,
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

            _resilient_commit(session, _apply_usage)
        session.close()
