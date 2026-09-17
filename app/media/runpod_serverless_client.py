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

The `input`/`output` payload shape inside that envelope is our own
choice, not a guess: the official runpod/worker-comfyui image's stock
handler only collects `images` node outputs and silently drops
`videos`/`gifs` (confirmed by reading its source, 2026-08-18) — not usable
for our SaveVideo-terminated LTX workflow. deploy/runpod_serverless/ builds
a custom image on that base with our own handler.py instead, deliberately
returning `{"video_base64": "<bytes>"}` to match what this module already
expects below — see that handler's own header comment for the full
rationale. `input: {"workflow": <ComfyUI API-format JSON>}` matches
app/media/ltx25_workflow.py::build_workflow()'s output directly, unchanged.
`output["video_url"]` is kept as a secondary fallback in case a future
version of our handler switches to uploading to storage and returning a
URL instead of inlining base64 (e.g. for very large files) — not currently
emitted by deploy/runpod_serverless/handler.py.
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
    def __init__(self, message, job_id=None):
        super().__init__(message)
        self.job_id = job_id


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
    # handler.py reports remux problems as a non-fatal field on a still-
    # "successful" job (video_base64 present) rather than failing the whole
    # job over it — log loudly rather than restructuring the return type
    # here (every caller currently expects raw bytes back).
    for warning_key in ("faststart_error",):
        if output.get(warning_key):
            logger.warning("RunPod Serverless job succeeded but reported %s: %s", warning_key, output[warning_key])
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


def run_inference_job(endpoint_id: str, workflow_json: dict = None, timeout_seconds: int = 5400,
                       poll_interval: int = _POLL_INTERVAL, reference_image_bytes: bytes = None,
                       reference_images: dict = None,
                       stats: dict = None) -> bytes:
    """Submits a ComfyUI workflow to a RunPod Serverless endpoint and blocks
    until it completes. Returns the output video's raw bytes. Raises
    RunPodServerlessError on a FAILED job or an unrecognized output shape,
    TimeoutError if it never reaches a terminal status in time.

    Default raised from 600s to 1200s — confirmed live 2026-08-29/30: three
    separate real jobs, on three different (freshly-recycled) workers,
    each failed with the worker's own internal "ComfyUI job did not
    complete within 600s" error (deploy/runpod_serverless/handler.py's
    _JOB_TIMEOUT_SECONDS, matching this client's own default), clustering
    tightly around 530-607s of actual executionTime rather than the wildly
    varying numbers a genuinely hung process would show — strong evidence
    this was real (if slow) progress running out of headroom, not a stuck
    worker, especially right after an image rebuild where a cold worker
    also has to pull a fresh multi-GB image and reload the LTX-2 checkpoint
    from the Network Volume before generation even starts. The worker's own
    COMFYUI_JOB_TIMEOUT_SECONDS was raised to match via the RunPod
    template's env vars.

    reference_image_bytes, when given, is base64-encoded and sent alongside
    the workflow — the worker's handler.py uploads it to ComfyUI's own
    input directory and wires it into the workflow's LoadImage node (see
    that file's _upload_reference_image), since LoadImage reads from a
    local filename, not inline bytes or a URL.

    reference_images (MSR / multi-subject-reference mode), when given, is
    a {filename: bytes} dict — mutually exclusive with reference_image_bytes
    (workflow_json is expected to already have its several LoadImage nodes
    pointed at these exact filenames via app.media.ltx25_workflow.
    build_workflow's reference_image_filenames param). Sent as
    reference_images_base64 so the worker's _upload_reference_images can
    upload each under its own distinct filename WITHOUT rewiring every
    LoadImage node the way the single-reference path does — see that
    function's docstring for why that would silently break multi-subject
    conditioning."""
    job_input = {"workflow": workflow_json}
    if reference_images is not None:
        job_input["reference_images_base64"] = {
            filename: base64.b64encode(image_bytes).decode("ascii")
            for filename, image_bytes in reference_images.items()
        }
    elif reference_image_bytes is not None:
        job_input["reference_image_base64"] = base64.b64encode(reference_image_bytes).decode("ascii")
    submit_resp = httpx.post(
        f"{_API_BASE}/{endpoint_id}/run",
        headers=_headers(),
        json={"input": job_input},
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
            # RunPod bills actual compute, and executionTime (ms) is the only
            # real measure of it. Cost was previously estimated from the
            # VIDEO's duration, which is not what is charged — a 12s video
            # takes ~226s of GPU, so that estimate was out by an order of
            # magnitude. Surfaced via an optional out-param so callers can
            # record a measured cost without changing this function's
            # return type.
            if stats is not None:
                execution_ms = data.get("executionTime")
                if isinstance(execution_ms, (int, float)):
                    stats["execution_seconds"] = execution_ms / 1000.0
                delay_ms = data.get("delayTime")
                if isinstance(delay_ms, (int, float)):
                    stats["delay_seconds"] = delay_ms / 1000.0
                stats["worker_id"] = data.get("workerId")
            return _extract_output_bytes(data.get("output"))
        if status == "FAILED":
            raise RunPodServerlessError(f"Serverless job {job_id} failed: {data.get('error') or data}", job_id=job_id)
        time.sleep(poll_interval)

    timeout_exc = TimeoutError(f"Serverless job {job_id} did not complete within {timeout_seconds}s")
    timeout_exc.job_id = job_id
    raise timeout_exc
