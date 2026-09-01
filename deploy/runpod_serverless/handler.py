"""RunPod Serverless handler for CultureToons' self-hosted LTX-2 video
inference. Runs inside the custom worker image built from this directory's
Dockerfile, as a drop-in replacement for the base `runpod/worker-comfyui`
image's own /handler.py (which only collects `images` node outputs and
silently drops `videos`/`gifs` — not usable for our SaveVideo-terminated
LTX workflow, see this directory's README).

Talks to the ComfyUI instance the base image's own /start.sh already
launches as a background process in this same container, on
127.0.0.1:8188 — same polling/extraction logic as
app/media/comfyui_client.py (validated against a live pod this session),
just localhost instead of a remote host/port and wrapped in RunPod's
handler(event) contract instead of being called directly from our backend.

Output contract: {"video_base64": "<base64 bytes>"} — chosen to match
app/media/runpod_serverless_client.py::_extract_output_bytes()'s existing
`video_base64` key exactly, since we control both ends of this contract
(unlike the base image's handler, whose shape we don't control). No changes
needed to runpod_serverless_client.py's output side as a result.

Two input shapes, added 2026-08-30 — see app/services/
culturetoon_selfhosted_video.py's module docstring for the full "why":
- `{"workflow": <ComfyUI API-format JSON>}` — the original single-clip
  contract, one LTX generation.
- `{"shot_workflows": [<workflow>, ...], "shot_reference_images_base64":
  [<base64-or-null>, ...]}` — one LTX generation PER SHOT, submitted to
  this SAME already-warm ComfyUI instance in order (so the model stays
  resident across all of them instead of N separate cold-ish jobs), then
  concatenated with ffmpeg. Real camera cuts + correct per-character
  identity instead of one continuous clip described by shared text.

Also optionally accepts narration alongside either shape:
- `narration_audio_base64` — pre-synthesized audio (the ElevenLabs opt-in
  path; synthesized on our own backend, since it needs the caller's own
  decrypted brand credential) — this worker just muxes it on with ffmpeg.
- `narration_text` — raw dialogue text for THIS worker to synthesize
  itself via Chatterbox (Resemble AI, MIT-licensed) on its own GPU before
  muxing — the default (free) path, confirmed via research 2026-08-30 to
  outperform ElevenLabs in blind listening tests at zero marginal API
  cost. narration_audio_base64 takes precedence when both are given.
"""
import base64
import io
import logging
import os
import subprocess
import tempfile
import time

import httpx
import runpod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("culturix.runpod_serverless_handler")

_COMFYUI_URL = "http://127.0.0.1:8188"
_STARTUP_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_STARTUP_TIMEOUT_SECONDS", "120"))
_JOB_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_JOB_TIMEOUT_SECONDS", "1200"))
_POLL_INTERVAL_SECONDS = 3

_chatterbox_model = None


def _wait_for_comfyui_ready() -> None:
    """The base image's /start.sh backgrounds ComfyUI and immediately execs
    this handler — there's no guarantee ComfyUI has finished loading models
    onto the GPU by the time the first job arrives, so block until
    /system_stats responds rather than racing it."""
    deadline = time.time() + _STARTUP_TIMEOUT_SECONDS
    last_error = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{_COMFYUI_URL}/system_stats", timeout=5)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"ComfyUI did not become ready within {_STARTUP_TIMEOUT_SECONDS}s: {last_error}")


def _submit_workflow(workflow_json: dict) -> str:
    resp = httpx.post(f"{_COMFYUI_URL}/prompt", json={"prompt": workflow_json}, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected the workflow: {resp.status_code} {resp.text[:2000]}")
    data = resp.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI returned no prompt_id: {data}")
    return prompt_id


def _wait_for_completion(prompt_id: str) -> dict:
    deadline = time.time() + _JOB_TIMEOUT_SECONDS
    while time.time() < deadline:
        resp = httpx.get(f"{_COMFYUI_URL}/history/{prompt_id}", timeout=20)
        resp.raise_for_status()
        entry = resp.json().get(prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error" or not status.get("completed", True):
                raise RuntimeError(f"ComfyUI job {prompt_id} failed: {status.get('messages')}")
            return entry
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"ComfyUI job {prompt_id} did not complete within {_JOB_TIMEOUT_SECONDS}s")


def _first_output_file(outputs: dict):
    """Returns the first video/gif/image file_info found in a history
    entry's outputs, or None."""
    for node_output in outputs.values():
        for key in ("gifs", "videos", "images"):
            files = node_output.get(key)
            if files:
                return files[0]
    return None


def _ensure_faststart(video_bytes: bytes) -> tuple:
    """ComfyUI's SaveVideo node (via av/ffmpeg muxing) writes the moov atom
    AFTER the mdat box by default — confirmed live 2026-08-29 by inspecting
    a real generated file's box layout (ftyp, free, mdat, moov, in that
    order). Most web/mobile video players and preview surfaces require (or
    strongly prefer) moov before mdat to start playback without fetching
    the entire file first; some refuse to open a non-faststart file at
    all, which is exactly what happened live — a delivered video "would
    not open" despite being a byte-valid MP4. `-movflags +faststart`
    remuxes losslessly (stream copy, no re-encode) to move moov to the
    front. Applied here ONCE, on the final video (after any multi-shot
    concat and narration mux — both of those also write fresh containers
    that would otherwise regress to moov-after-mdat), so every caller of
    this endpoint gets a playable file rather than needing to know to
    remux it themselves.

    Returns (bytes, diagnostic) rather than swallowing failures silently —
    confirmed live 2026-08-29: even on a freshly-built image running on a
    provably brand-new worker (never-before-seen workerId, ~9.5min cold
    execution time ruling out a stale cached image), the delivered file
    STILL came back non-faststart, meaning this remux is failing inside
    its own try/except for a reason not yet identified — there's no way
    to see this container's internal logs from the caller side, so the
    previous silent fallback left that failure completely invisible.
    Surfacing the actual exception in the response is what a future
    debugging pass needs instead of guessing again."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as src:
        src.write(video_bytes)
        src_path = src.name
    dst_path = src_path + ".faststart.mp4"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-c", "copy", "-movflags", "+faststart", dst_path],
            capture_output=True, timeout=60,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr.decode("utf-8", errors="replace")[-800:]
            return video_bytes, f"ffmpeg exit {result.returncode}: {stderr_tail}"
        with open(dst_path, "rb") as f:
            return f.read(), None
    except Exception as exc:
        logger.exception("faststart remux failed — returning the original (non-faststart) bytes")
        return video_bytes, f"{type(exc).__name__}: {exc}"
    finally:
        for path in (src_path, dst_path):
            try:
                os.remove(path)
            except OSError:
                pass


def _fetch_file_bytes(file_info: dict) -> bytes:
    params = {
        "filename": file_info["filename"],
        "subfolder": file_info.get("subfolder", ""),
        "type": file_info.get("type", "output"),
    }
    resp = httpx.get(f"{_COMFYUI_URL}/view", params=params, timeout=120)
    resp.raise_for_status()
    return resp.content


def _download_output_bytes(history_entry: dict, prompt_id: str) -> bytes:
    """Returns the raw (not yet faststart-remuxed) output bytes for one
    shot's completed prompt — faststart is applied once, at the very end
    of the whole job (see _ensure_faststart), not per-shot here."""
    file_info = _first_output_file(history_entry.get("outputs") or {})
    if file_info:
        return _fetch_file_bytes(file_info)

    # Confirmed live 2026-08-28: a retried submission of an IDENTICAL
    # workflow (same seed/prompt/duration — e.g. run_inference_job_with_
    # allocation_retry resubmitting after a client-side timeout, when the
    # first attempt actually finished server-side) hits ComfyUI's own
    # execution cache. status_str is "success" and every node shows up
    # under execution_cached, but THIS prompt_id's own history entry never
    # gets its outputs populated — the real file reference lives on
    # whichever earlier prompt_id first computed it. Fall back to
    # scanning the bulk /history for the most recent entry (any prompt_id)
    # that actually has a file output, rather than failing a job whose
    # result already exists.
    logger.warning(
        "Prompt %s completed with empty outputs (likely a ComfyUI cache hit on a "
        "retried/duplicate submission) — scanning /history for the real output.",
        prompt_id,
    )
    resp = httpx.get(f"{_COMFYUI_URL}/history", params={"max_items": 50}, timeout=20)
    resp.raise_for_status()
    entries = resp.json()
    candidates = [
        (entry.get("prompt", [0])[0], pid, entry)
        for pid, entry in entries.items()
        if pid != prompt_id and _first_output_file(entry.get("outputs") or {})
    ]
    if not candidates:
        raise RuntimeError(f"No file output found in ComfyUI history entry: {history_entry}")
    # prompt[0] is ComfyUI's own monotonically increasing queue number —
    # a reliable recency ordering independent of any timestamp field.
    candidates.sort(key=lambda c: c[0])
    _, _, best_entry = candidates[-1]
    best_file_info = _first_output_file(best_entry["outputs"])
    return _fetch_file_bytes(best_file_info)


def _upload_reference_image(image_base64: str) -> str:
    """Uploads a reference photo to ComfyUI's own /upload/image endpoint so
    a LoadImage node in the workflow can reference it by filename —
    LoadImage reads from ComfyUI's local input directory, not a URL or
    inline bytes, so the image has to land there before the workflow is
    submitted. Returns the filename ComfyUI actually stored it under.

    Always requests the same literal "reference.png" name (overwrite=true)
    — safe even across a multi-shot job's sequential per-shot uploads,
    since each shot's own upload+submit+wait happens strictly in order
    before the next shot's upload ever runs (see _generate_single_shot /
    the multi-shot loop in handler())."""
    image_bytes = base64.b64decode(image_base64)
    resp = httpx.post(
        f"{_COMFYUI_URL}/upload/image",
        files={"image": ("reference.png", image_bytes, "image/png")},
        data={"overwrite": "true"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    filename = data.get("name")
    if not filename:
        raise RuntimeError(f"ComfyUI /upload/image returned no filename: {data}")
    return filename


_LORA_LOAD_MAX_RETRIES = 2  # up to 3 total attempts per shot


def _is_transient_lora_load_error(exc: Exception) -> bool:
    """Confirmed live 2026-09-01: LoraLoaderModelOnly intermittently raises
    `RuntimeError: shape '[...]' is invalid for input of size N` when
    loading a LoRA off the Network Volume — NOT because the file is bad
    (the same file, byte-verified via the official safetensors library and
    hash-confirmed identical to a known-good copy, failed on a DIFFERENT
    tensor on a different attempt, and succeeded outright on others). This
    matches a network-filesystem mmap reliability issue (a partial/torn
    read racing the buffer slice in comfy/utils.py's load_safetensors),
    not file corruption — retrying the same load is the correct response,
    not re-fetching or regenerating the LoRA. Narrowly matched (not a bare
    `except RuntimeError`) so a genuinely different, deterministic
    workflow error still fails fast instead of burning 3x the time on a
    guaranteed-repeat failure."""
    text = str(exc)
    return "LoraLoaderModelOnly" in text and "is invalid for input of size" in text


def _generate_single_shot(workflow_json: dict, reference_image_base64: str = None) -> bytes:
    """Uploads the shot's own reference image (if given), submits its
    workflow, waits for completion, and returns the raw (not yet
    faststart-remuxed) video bytes. Shared by both the legacy single-clip
    path and each iteration of the multi-shot loop in handler() below.

    Retries the submit+wait step (not the reference-image upload, which
    doesn't fail this way) on the transient LoRA-load error above — a
    fresh prompt_id and a fresh read of the same file is enough to clear
    it, confirmed live 2026-09-01 against a file that had already failed
    twice on different tensors."""
    if reference_image_base64:
        uploaded_filename = _upload_reference_image(reference_image_base64)
        load_image_nodes = [
            node for node in workflow_json.values() if node.get("class_type") == "LoadImage"
        ]
        if not load_image_nodes:
            raise RuntimeError(
                "A reference image was provided but this shot's workflow has no LoadImage node to wire it into"
            )
        for node in load_image_nodes:
            node["inputs"]["image"] = uploaded_filename

    last_exc = None
    for attempt in range(_LORA_LOAD_MAX_RETRIES + 1):
        prompt_id = _submit_workflow(workflow_json)
        logger.info("Submitted ComfyUI prompt %s (attempt %d/%d)", prompt_id, attempt + 1, _LORA_LOAD_MAX_RETRIES + 1)
        try:
            history_entry = _wait_for_completion(prompt_id)
            return _download_output_bytes(history_entry, prompt_id)
        except RuntimeError as exc:
            if not _is_transient_lora_load_error(exc) or attempt == _LORA_LOAD_MAX_RETRIES:
                raise
            last_exc = exc
            logger.warning(
                "Transient LoRA-load error on prompt %s (attempt %d/%d) — retrying: %s",
                prompt_id, attempt + 1, _LORA_LOAD_MAX_RETRIES + 1, exc,
            )
    raise last_exc  # unreachable, satisfies static analysis


def _concat_videos(video_byte_list: list) -> bytes:
    """Concatenates N shot videos (in order) into one file via ffmpeg's
    concat demuxer with -c copy (lossless, no re-encode). Every shot comes
    from the same workflow template (same resolution/fps/codec), so a
    straight stream-copy concat is safe without needing scale/pad
    normalization (unlike stitching Kling-generated and self-hosted
    segments together, which DOES need that — see app/services/
    culturetoon_episode.py)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        segment_paths = []
        for i, video_bytes in enumerate(video_byte_list):
            seg_path = os.path.join(tmp_dir, f"shot_{i}.mp4")
            with open(seg_path, "wb") as f:
                f.write(video_bytes)
            segment_paths.append(seg_path)
        list_path = os.path.join(tmp_dir, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in segment_paths:
                f.write(f"file '{p}'\n")
        output_path = os.path.join(tmp_dir, "concatenated.mp4")
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr.decode("utf-8", errors="replace")[-800:]
            raise RuntimeError(f"ffmpeg failed concatenating shot videos (exit {result.returncode}): {stderr_tail}")
        with open(output_path, "rb") as f:
            return f.read()


def _extract_last_frame_png(video_bytes: bytes) -> bytes:
    """Returns the final frame of a shot as PNG bytes, for use as the NEXT
    shot's image-to-video anchor (see the chaining logic in handler()).

    Why: every shot used to be an independent generation anchored on the
    speaking character's solo portrait, so nothing carried across a cut —
    no shared scene, lighting or character positions, and only ever one
    character in frame. Carrying the previous shot's last frame forward is
    LTX's own documented first/last-frame pattern and is what makes
    consecutive shots read as one continuous scene with characters
    actually present together.

    `-sseof -1` seeks to one second before the end and `-update 1` keeps
    overwriting a single output image, so whatever lands last IS the final
    frame — more reliable than computing a timestamp from the duration,
    which needs an exact frame count we don't have here."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = os.path.join(tmp_dir, "shot.mp4")
        dst = os.path.join(tmp_dir, "last.png")
        with open(src, "wb") as f:
            f.write(video_bytes)
        result = subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-1", "-i", src, "-update", "1", "-q:v", "2", dst],
            capture_output=True, timeout=60,
        )
        if result.returncode != 0 or not os.path.exists(dst):
            stderr_tail = result.stderr.decode("utf-8", errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg could not extract the last frame (exit {result.returncode}): {stderr_tail}")
        with open(dst, "rb") as f:
            return f.read()


def _get_chatterbox_model():
    """Lazily loads Chatterbox once per worker process and reuses it
    across every job that process handles — model loading is the slow
    part (same reasoning ComfyUI itself stays resident across jobs rather
    than reloading per request)."""
    global _chatterbox_model
    if _chatterbox_model is None:
        from chatterbox.tts import ChatterboxTTS
        logger.info("Loading Chatterbox TTS model (first use this worker process)...")
        _chatterbox_model = ChatterboxTTS.from_pretrained(device="cuda")
    return _chatterbox_model


def _synthesize_narration_chatterbox(text: str) -> tuple:
    """Synthesizes narration directly on THIS worker's own GPU via
    Chatterbox (Resemble AI, MIT-licensed, github.com/resemble-ai/
    chatterbox) instead of any external TTS API — confirmed via real
    research 2026-08-30 to outperform ElevenLabs in blind listening tests
    (65.3%/24.5% preference for Chatterbox Turbo in Resemble AI's own
    reported results), at zero marginal cost since it reuses the same GPU
    already being paid for by this job's video generation. No reference-
    voice cloning yet (would need a stored per-character voice sample —
    not something any CharacterVariant has today), so every character
    currently shares Chatterbox's own default voice; voice cloning is a
    natural follow-up once character voice samples exist.

    Returns (wav_bytes, diagnostic) — best-effort like every other
    synthesis/mux step in this file: a failure here should degrade the
    whole generation to silent video, not fail it outright."""
    try:
        model = _get_chatterbox_model()
        wav = model.generate(text)
        return _tensor_to_wav_bytes(wav, model.sr), None
    except Exception as exc:
        logger.exception("Chatterbox narration synthesis failed")
        return None, f"{type(exc).__name__}: {exc}"


def _tensor_to_wav_bytes(wav, sample_rate: int) -> bytes:
    """Encodes Chatterbox's output tensor as WAV using only the Python
    stdlib `wave` module.

    Deliberately NOT torchaudio.save(): confirmed live 2026-09-01 that it
    raised `ImportError: TorchCodec is required for save_with_torchcodec`
    on the deployed image — newer torchaudio routes save() through
    torchcodec, which isn't installed. Every generated video came back
    silent because of it, and the failure was invisible until the client
    stopped discarding this handler's chatterbox_error field.

    Installing torchcodec would be the obvious fix, but it resolves against
    the same torch/CUDA dependency graph that a chatterbox-tts install
    already silently broke once (see the Dockerfile's NCCL note — every
    worker crash-looped on `undefined symbol: ncclCommResume` until the
    pin/restore was widened). Writing a WAV header needs no ML library at
    all, so this sidesteps that whole risk class rather than adding another
    package to it."""
    import wave

    import numpy as np

    samples = wav.detach().to("cpu").numpy() if hasattr(wav, "detach") else np.asarray(wav)
    samples = np.atleast_2d(samples)          # (channels, frames)
    channels = samples.shape[0]
    # float32 in [-1, 1] -> int16 PCM. Clipped first: Chatterbox output can
    # exceed unity slightly, which would wrap around into loud noise rather
    # than simply saturating.
    if np.issubdtype(samples.dtype, np.floating):
        samples = np.clip(samples, -1.0, 1.0)
        samples = (samples * 32767.0).astype(np.int16)
    else:
        samples = samples.astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)                      # int16
        f.setframerate(int(sample_rate))
        f.writeframes(samples.T.tobytes())     # interleave to (frames, channels)
    return buf.getvalue()


def _mux_narration_audio(video_bytes: bytes, audio_bytes: bytes, audio_format: str = "mp3") -> tuple:
    """Muxes narration audio (either pre-synthesized via ElevenLabs on our
    backend, format="mp3", or synthesized right here via Chatterbox,
    format="wav") directly onto the finished video on the worker, instead
    of the backend downloading a silent video and running its own local
    ffmpeg pass. The Dockerfile already installs ffmpeg for the faststart
    remux above, so this needs no new dependency.

    Uses -shortest, UNLIKE app/services/culturetoon_video.py::_dub_dialogue
    (the Kling path's equivalent) — confirmed live 2026-08-30 this needs
    the opposite choice here: _dub_dialogue omits -shortest because Kling's
    requested duration is only a loose guess at what Kling's API actually
    returns, so trimming would risk cutting the VIDEO's tail short whenever
    dialogue finished a little early. Self-hosted is different — each
    shot's video length is the caller's own precise, authored
    duration_seconds (see app/services/culturetoon_selfhosted_video.py),
    while narration is always synthesized for the FULL script's dialogue
    regardless. Without -shortest, a short test override once came back
    with 9.7s of video and 50s of audio muxed onto it — confirmed live by
    inspecting the actual output file's stream durations. -shortest trims
    the mismatched audio down to the video's own length instead.

    Returns (bytes, diagnostic) — best-effort like _ensure_faststart above:
    a muxing failure degrades to the silent (but still real, animated)
    video rather than failing a generation that otherwise succeeded."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as vf:
        vf.write(video_bytes)
        video_path = vf.name
    with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as af:
        af.write(audio_bytes)
        audio_path = af.name
    output_path = video_path + ".dubbed.mp4"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-map", "0:v:0", "-map", "1:a:0", "-shortest", output_path],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr.decode("utf-8", errors="replace")[-800:]
            return video_bytes, f"ffmpeg exit {result.returncode}: {stderr_tail}"
        with open(output_path, "rb") as f:
            return f.read(), None
    except Exception as exc:
        logger.exception("Narration mux failed — returning the silent video")
        return video_bytes, f"{type(exc).__name__}: {exc}"
    finally:
        for path in (video_path, audio_path, output_path):
            try:
                os.remove(path)
            except OSError:
                pass


def _object_info_response(input_data: dict) -> dict:
    """Diagnostic branch: returns ComfyUI's own node schemas.

    Exists because this is a SERVERLESS image — its CMD is /start.sh, so
    unlike runpod/base it ships no SSH daemon, and renting a pod from it
    just to `curl 127.0.0.1:8188/object_info` doesn't work (confirmed live
    2026-09-01: no SSH port ever exposed). The endpoint itself is the only
    way in.

    Needed to convert official ComfyUI workflow templates from UI format
    to the API format this handler consumes: UI format stores widget values
    positionally with no names, and only /object_info knows the real input
    names. Guessing them is how the LTX-2.3 graph silently lost its
    LTXVConditioning node.

    `classes` (optional) returns full schemas for just those node classes —
    the full /object_info is several MB and risks the response size limit,
    so the default returns only the class-name list."""
    resp = httpx.get(f"{_COMFYUI_URL}/object_info", timeout=180)
    resp.raise_for_status()
    info = resp.json()
    wanted = input_data.get("classes")
    if wanted:
        return {
            "object_info": {c: info[c] for c in wanted if c in info},
            "missing": [c for c in wanted if c not in info],
            "total_classes": len(info),
        }
    return {"class_names": sorted(info.keys()), "total_classes": len(info)}


def handler(event: dict) -> dict:
    input_data = event.get("input") or {}
    if input_data.get("debug_object_info"):
        try:
            _wait_for_comfyui_ready()
            return _object_info_response(input_data)
        except Exception as exc:
            logger.exception("object_info diagnostic failed")
            return {"error": f"{type(exc).__name__}: {exc}"}

    shot_workflows = input_data.get("shot_workflows")
    workflow_json = input_data.get("workflow")
    if not shot_workflows and not workflow_json:
        return {"error": "input.workflow or input.shot_workflows is required (ComfyUI API-format JSON)"}

    try:
        _wait_for_comfyui_ready()

        if shot_workflows:
            shot_reference_images_base64 = input_data.get("shot_reference_images_base64") or [None] * len(shot_workflows)
            # Parallel to shot_workflows: True means "anchor this shot on the
            # PREVIOUS shot's last frame instead of this speaker's solo
            # portrait", which is what makes consecutive shots read as one
            # continuous scene with characters present together rather than
            # isolated clips glued end to end. Absent/short (older backend)
            # => all False => previous per-shot-portrait behavior, so this
            # stays backward compatible with a client that doesn't send it.
            chain_flags = input_data.get("shot_chain_from_previous") or []
            chain_flags = list(chain_flags) + [False] * (len(shot_workflows) - len(chain_flags))

            shot_videos = []
            previous_frame_b64 = None
            for i, (shot_workflow, ref_b64) in enumerate(zip(shot_workflows, shot_reference_images_base64)):
                anchor_b64, anchor_kind = ref_b64, "portrait"
                if i > 0 and chain_flags[i] and previous_frame_b64:
                    anchor_b64, anchor_kind = previous_frame_b64, "previous frame"
                logger.info("Generating shot %d/%d (anchor: %s)", i + 1, len(shot_workflows), anchor_kind)
                shot_bytes = _generate_single_shot(shot_workflow, anchor_b64)
                shot_videos.append(shot_bytes)

                # Best-effort: a failure to extract the carry-forward frame
                # degrades the NEXT shot to its own portrait anchor (i.e.
                # the old behavior) rather than failing a generation that
                # has already produced real video.
                try:
                    previous_frame_b64 = base64.b64encode(_extract_last_frame_png(shot_bytes)).decode("ascii")
                except Exception:
                    logger.exception("Could not extract shot %d's last frame — next shot falls back to its portrait", i + 1)
                    previous_frame_b64 = None
            video_bytes = shot_videos[0] if len(shot_videos) == 1 else _concat_videos(shot_videos)
        else:
            video_bytes = _generate_single_shot(workflow_json, input_data.get("reference_image_base64"))

        narration_audio_base64 = input_data.get("narration_audio_base64")
        narration_text = input_data.get("narration_text")
        chatterbox_error = None
        narration_mux_error = None
        narration_bytes = None
        audio_format = "mp3"
        if narration_audio_base64:
            narration_bytes = base64.b64decode(narration_audio_base64)
        elif narration_text:
            audio_format = "wav"
            narration_bytes, chatterbox_error = _synthesize_narration_chatterbox(narration_text)

        if narration_bytes:
            video_bytes, narration_mux_error = _mux_narration_audio(video_bytes, narration_bytes, audio_format)

        # Applied ONCE here, on the final video — after any multi-shot
        # concat and/or narration mux, both of which write fresh
        # containers that would otherwise regress to moov-after-mdat.
        video_bytes, faststart_error = _ensure_faststart(video_bytes)

        result = {"video_base64": base64.b64encode(video_bytes).decode("ascii")}
        if faststart_error:
            # Non-fatal — the caller still gets a valid (just non-faststart)
            # file — but surfaced instead of silently swallowed, since a
            # prior version of this hid a real, still-unexplained remux
            # failure completely from the caller.
            result["faststart_error"] = faststart_error
        if narration_mux_error:
            result["narration_mux_error"] = narration_mux_error
        if chatterbox_error:
            result["chatterbox_error"] = chatterbox_error
        return result
    except Exception as exc:
        logger.exception("Job failed")
        return {"error": str(exc)}


runpod.serverless.start({"handler": handler})
