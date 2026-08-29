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
needed to runpod_serverless_client.py as a result.
"""
import base64
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
_JOB_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_JOB_TIMEOUT_SECONDS", "600"))
_POLL_INTERVAL_SECONDS = 3


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
    """Returns (file_info, is_video) — is_video distinguishes the "videos"
    key (needs the faststart remux below) from "gifs"/"images" (not mp4
    containers, remuxing would be meaningless or break them)."""
    for node_output in outputs.values():
        for key in ("gifs", "videos", "images"):
            files = node_output.get(key)
            if files:
                return files[0], key == "videos"
    return None, False


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
    front. Applied here once, server-side, so every caller of this
    endpoint gets a playable file rather than needing to know to remux it
    themselves.

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


def _fetch_file_bytes(file_info: dict, is_video: bool) -> tuple:
    params = {
        "filename": file_info["filename"],
        "subfolder": file_info.get("subfolder", ""),
        "type": file_info.get("type", "output"),
    }
    resp = httpx.get(f"{_COMFYUI_URL}/view", params=params, timeout=120)
    resp.raise_for_status()
    if is_video:
        return _ensure_faststart(resp.content)
    return resp.content, None


def _download_output_bytes(history_entry: dict, prompt_id: str) -> tuple:
    file_info, is_video = _first_output_file(history_entry.get("outputs") or {})
    if file_info:
        return _fetch_file_bytes(file_info, is_video)

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
        if pid != prompt_id and _first_output_file(entry.get("outputs") or {})[0]
    ]
    if not candidates:
        raise RuntimeError(f"No file output found in ComfyUI history entry: {history_entry}")
    # prompt[0] is ComfyUI's own monotonically increasing queue number —
    # a reliable recency ordering independent of any timestamp field.
    candidates.sort(key=lambda c: c[0])
    _, _, best_entry = candidates[-1]
    best_file_info, best_is_video = _first_output_file(best_entry["outputs"])
    return _fetch_file_bytes(best_file_info, best_is_video)


def _upload_reference_image(image_base64: str) -> str:
    """Uploads a reference photo to ComfyUI's own /upload/image endpoint so
    a LoadImage node in the workflow can reference it by filename —
    LoadImage reads from ComfyUI's local input directory, not a URL or
    inline bytes, so the image has to land there before the workflow is
    submitted. Returns the filename ComfyUI actually stored it under."""
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


def handler(event: dict) -> dict:
    input_data = event.get("input") or {}
    workflow_json = input_data.get("workflow")
    if not workflow_json:
        return {"error": "input.workflow is required (ComfyUI API-format JSON)"}

    try:
        _wait_for_comfyui_ready()

        reference_image_base64 = input_data.get("reference_image_base64")
        if reference_image_base64:
            uploaded_filename = _upload_reference_image(reference_image_base64)
            load_image_nodes = [
                node for node in workflow_json.values() if node.get("class_type") == "LoadImage"
            ]
            if not load_image_nodes:
                raise RuntimeError(
                    "reference_image_base64 was provided but the workflow has no LoadImage node to wire it into"
                )
            for node in load_image_nodes:
                node["inputs"]["image"] = uploaded_filename

        prompt_id = _submit_workflow(workflow_json)
        logger.info("Submitted ComfyUI prompt %s", prompt_id)
        history_entry = _wait_for_completion(prompt_id)
        video_bytes, faststart_error = _download_output_bytes(history_entry, prompt_id)
        result = {"video_base64": base64.b64encode(video_bytes).decode("ascii")}
        if faststart_error:
            # Non-fatal — the caller still gets a valid (just non-faststart)
            # file — but surfaced instead of silently swallowed, since a
            # prior version of this hid a real, still-unexplained remux
            # failure completely from the caller.
            result["faststart_error"] = faststart_error
        return result
    except Exception as exc:
        logger.exception("Job failed")
        return {"error": str(exc)}


runpod.serverless.start({"handler": handler})
