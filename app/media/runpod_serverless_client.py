"""RunPod Serverless client for the self-hosted video inference path —
replaces app/media/comfyui_client.py's direct Pod-HTTP calls for the
automated batch runner (app/services/culturetoon_selfhosted_batch.py).
comfyui_client.py itself is unchanged and still used for the spec's own
manual first-quality-check pass against a plain on-demand Pod, before a
Serverless endpoint exists.

RunPod's Serverless job-submission contract (POST /run -> {id}, poll
GET /status/{id} -> {status, output}) is platform-stable and documented at
https://docs.runpod.io/serverless/endpoints/job-operations — that outer
contract is what this module builds against with confidence.

UNVERIFIED: the `input`/`output` payload SHAPE inside that envelope is
specific to whichever ComfyUI-on-Serverless handler image is actually
deployed (the spec names artokun/comfyui-runpod as the reference). This
module assumes `input: {"workflow": <ComfyUI API-format JSON>}` and looks
for output video bytes at `output["video_base64"]` (base64-encoded) or
`output["video_url"]` (a fetchable URL), trying both — confirm against
your actual deployed handler's README/source once it's live and adjust
_extract_output_bytes() if the real keys differ.
"""
import base64
import logging
import os
import time

import httpx

logger = logging.getLogger("culturix.media.runpod_serverless_client")

_API_BASE = "https://api.runpod.ai/v2"
_POLL_INTERVAL = 10  # seconds
_TERMINAL_STATUSES = {"COMPLETED", "FAILED"}


class RunPodServerlessError(Exception):
    pass


def _api_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "")
    if not key:
        raise RuntimeError("RUNPOD_API_KEY must be set")
    return key


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


def _extract_output_bytes(output: dict) -> bytes:
    if not output:
        raise RunPodServerlessError("Serverless job completed with no output")
    if "video_base64" in output:
        return base64.b64decode(output["video_base64"])
    if "video_url" in output:
        resp = httpx.get(output["video_url"], timeout=120)
        resp.raise_for_status()
        return resp.content
    raise RunPodServerlessError(
        f"Serverless output has neither 'video_base64' nor 'video_url' — got keys: {list(output.keys())}. "
        "This means the deployed handler's output shape differs from what this client assumes — see this "
        "module's own header comment."
    )


def run_inference_job(endpoint_id: str, workflow_json: dict, timeout_seconds: int = 600,
                       poll_interval: int = _POLL_INTERVAL) -> bytes:
    """Submits a ComfyUI workflow to a RunPod Serverless endpoint and blocks
    until it completes. Returns the output video's raw bytes. Raises
    RunPodServerlessError on a FAILED job or an unrecognized output shape,
    TimeoutError if it never reaches a terminal status in time."""
    submit_resp = httpx.post(
        f"{_API_BASE}/{endpoint_id}/run",
        headers=_headers(),
        json={"input": {"workflow": workflow_json}},
        timeout=30,
    )
    submit_resp.raise_for_status()
    job_id = submit_resp.json().get("id")
    if not job_id:
        raise RunPodServerlessError(f"RunPod Serverless returned no job id: {submit_resp.json()}")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status_resp = httpx.get(f"{_API_BASE}/{endpoint_id}/status/{job_id}", headers=_headers(), timeout=20)
        status_resp.raise_for_status()
        data = status_resp.json()
        status = data.get("status")
        if status == "COMPLETED":
            return _extract_output_bytes(data.get("output"))
        if status == "FAILED":
            raise RunPodServerlessError(f"Serverless job {job_id} failed: {data.get('error') or data}")
        time.sleep(poll_interval)

    raise TimeoutError(f"Serverless job {job_id} did not complete within {timeout_seconds}s")
