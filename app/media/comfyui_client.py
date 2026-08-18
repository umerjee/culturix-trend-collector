"""ComfyUI headless API client — submit a workflow, poll for completion,
fetch the output. Polling (not websocket) deliberately: this codebase has
zero websocket usage anywhere and one consistent HTTP client convention
(httpx), matching KlingProvider's own poll-loop shape (app/media/video.py)
exactly rather than introducing a new dependency for a job-completion check
ComfyUI's REST-ish API already supports via /history.
"""
import logging
import time

import httpx

logger = logging.getLogger("culturix.media.comfyui_client")

_POLL_INTERVAL = 10  # seconds


class ComfyUIError(Exception):
    pass


def submit_workflow(comfyui_url: str, workflow_json: dict) -> str:
    """POSTs a workflow (API-format JSON, keyed by node id) to /prompt.
    Returns the prompt_id used to track completion."""
    resp = httpx.post(f"{comfyui_url}/prompt", json={"prompt": workflow_json}, timeout=30)
    if resp.status_code != 200:
        raise ComfyUIError(f"ComfyUI rejected the workflow: {resp.status_code} {resp.text[:2000]}")
    data = resp.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise ComfyUIError(f"ComfyUI returned no prompt_id: {data}")
    return prompt_id


def wait_for_completion(comfyui_url: str, prompt_id: str, timeout_seconds: int = 600,
                         poll_interval: int = _POLL_INTERVAL) -> dict:
    """Polls GET /history/{prompt_id} until the job appears there (ComfyUI
    only adds an entry once execution finishes, success or failure) and
    returns that history entry. Raises ComfyUIError if the job's own status
    reports an error, TimeoutError if it never completes in time."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        resp = httpx.get(f"{comfyui_url}/history/{prompt_id}", timeout=20)
        resp.raise_for_status()
        history = resp.json()
        entry = history.get(prompt_id)
        if entry:
            status = (entry.get("status") or {})
            if status.get("status_str") == "error" or not status.get("completed", True):
                messages = status.get("messages") or []
                raise ComfyUIError(f"ComfyUI job {prompt_id} failed: {messages}")
            return entry
        time.sleep(poll_interval)
    raise TimeoutError(f"ComfyUI job {prompt_id} did not complete within {timeout_seconds}s")


def download_output(comfyui_url: str, history_entry: dict) -> bytes:
    """Finds the first video/file output in a completed job's history entry
    and downloads its bytes via GET /view."""
    outputs = history_entry.get("outputs") or {}
    for node_id, node_output in outputs.items():
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
            resp = httpx.get(f"{comfyui_url}/view", params=params, timeout=120)
            resp.raise_for_status()
            return resp.content
    raise ComfyUIError(f"No file output found in ComfyUI history entry: {history_entry}")
