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


def _download_output_bytes(history_entry: dict) -> bytes:
    outputs = history_entry.get("outputs") or {}
    for node_output in outputs.values():
        for key in ("gifs", "videos", "images"):
            files = node_output.get(key)
            if not files:
                continue
            file_info = files[0]
            params = {
                "filename": file_info["filename"],
                "subfolder": file_info.get("subfolder", ""),
                "type": file_info.get("type", "output"),
            }
            resp = httpx.get(f"{_COMFYUI_URL}/view", params=params, timeout=120)
            resp.raise_for_status()
            return resp.content
    raise RuntimeError(f"No file output found in ComfyUI history entry: {history_entry}")


def handler(event: dict) -> dict:
    workflow_json = (event.get("input") or {}).get("workflow")
    if not workflow_json:
        return {"error": "input.workflow is required (ComfyUI API-format JSON)"}

    try:
        _wait_for_comfyui_ready()
        prompt_id = _submit_workflow(workflow_json)
        logger.info("Submitted ComfyUI prompt %s", prompt_id)
        history_entry = _wait_for_completion(prompt_id)
        video_bytes = _download_output_bytes(history_entry)
        return {"video_base64": base64.b64encode(video_bytes).decode("ascii")}
    except Exception as exc:
        logger.exception("Job failed")
        return {"error": str(exc)}


runpod.serverless.start({"handler": handler})
