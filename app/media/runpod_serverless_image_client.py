"""RunPod Serverless client for the self-hosted IMAGE editing path
(Qwen-Image-Edit) — a separate module from runpod_serverless_client.py
because the job contract is genuinely different, not just a different
model:

  - Video (runpod_serverless_client.py) runs a CUSTOM worker image with
    our own handler.py, since the stock runpod/worker-comfyui handler only
    collects `images` node outputs and silently drops `videos`/`gifs`
    (confirmed 2026-08-18 — see that module's own header comment).
  - Image editing uses the STOCK, unmodified runpod/worker-comfyui image —
    confirmed 2026-08-20 by reading its real source
    (github.com/runpod-workers/worker-comfyui): its handler already
    collects SaveImage outputs and returns them as
    `output.images: [{"filename", "type": "base64"|"s3_url", "data"}]`,
    and separately accepts `input.images: [{"name", "image": "<base64 or
    data URI>"}]` to upload a reference photo into ComfyUI's input folder
    before running the workflow (validated against handler.py's
    validate_input()/upload_images() directly, not the docs). No custom
    handler or Dockerfile beyond a corrected extra_model_paths.yaml is
    needed for this path — see deploy/runpod_serverless_image/.

Submission/polling outer contract (POST /run -> {id}, poll
GET /status/{id} -> {status, output}) is the same RunPod-documented shape
runpod_serverless_client.py already builds against.
"""
import base64
import logging
import os
import time
import uuid as _uuid

import httpx

logger = logging.getLogger("culturix.media.runpod_serverless_image_client")

_API_BASE = "https://api.runpod.ai/v2"
_POLL_INTERVAL = 5  # seconds — image jobs are much faster than video, poll tighter
_DEFAULT_ALLOCATION_MAX_RETRIES = 1
_DEFAULT_ALLOCATION_BACKOFF_SECONDS = 30


class RunPodImageServerlessError(Exception):
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
        raise RunPodImageServerlessError("Serverless job completed with no output")
    images = output.get("images")
    if not images:
        raise RunPodImageServerlessError(
            f"Serverless output has no 'images' — got keys: {list(output.keys())}. "
            "This means the workflow's SaveImage node didn't produce output, or the deployed "
            "image differs from the stock runpod/worker-comfyui contract this client assumes."
        )
    first = images[0]
    if first.get("type") == "base64":
        return base64.b64decode(first["data"])
    if first.get("type") == "s3_url":
        resp = httpx.get(first["data"], timeout=60)
        resp.raise_for_status()
        return resp.content
    raise RunPodImageServerlessError(f"Unrecognized image output type: {first.get('type')!r}")


def run_edit_job(endpoint_id: str, workflow_json: dict, reference_image_bytes: bytes,
                  reference_image_filename: str, timeout_seconds: int = 180,
                  poll_interval: int = _POLL_INTERVAL) -> bytes:
    """Submits a Qwen-Image-Edit workflow + its reference image to a RunPod
    Serverless endpoint and blocks until it completes. reference_image_
    filename must match whatever qwen_image_workflow.build_workflow() was
    given (its LoadImage node reads this exact name back out of the
    job's uploaded images). Returns the output image's raw bytes. Raises
    RunPodImageServerlessError on a FAILED job or unrecognized output
    shape, TimeoutError if it never reaches a terminal status in time."""
    input_image_b64 = base64.b64encode(reference_image_bytes).decode("ascii")
    submit_resp = httpx.post(
        f"{_API_BASE}/{endpoint_id}/run",
        headers=_headers(),
        json={
            "input": {
                "workflow": workflow_json,
                "images": [{"name": reference_image_filename, "image": input_image_b64}],
            }
        },
        timeout=30,
    )
    submit_resp.raise_for_status()
    job_id = submit_resp.json().get("id")
    if not job_id:
        raise RunPodImageServerlessError(f"RunPod Serverless returned no job id: {submit_resp.json()}")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status_resp = httpx.get(f"{_API_BASE}/{endpoint_id}/status/{job_id}", headers=_headers(), timeout=20)
        status_resp.raise_for_status()
        data = status_resp.json()
        status = data.get("status")
        if status == "COMPLETED":
            output = data.get("output") or {}
            if "error" in output:
                raise RunPodImageServerlessError(f"Serverless job {job_id} reported an error: {output}")
            return _extract_output_bytes(output)
        if status == "FAILED":
            raise RunPodImageServerlessError(f"Serverless job {job_id} failed: {data.get('error') or data}")
        time.sleep(poll_interval)

    raise TimeoutError(f"Serverless job {job_id} did not complete within {timeout_seconds}s")


def run_edit_job_with_allocation_retry(endpoint_id: str, workflow_json: dict, reference_image_bytes: bytes,
                                        reference_image_filename: str, timeout_seconds: int = 180,
                                        poll_interval: int = _POLL_INTERVAL,
                                        max_retries: int = None, backoff_seconds: float = None) -> bytes:
    """Wraps run_edit_job with a retry around allocation failures, same
    reasoning as runpod_serverless_client.run_inference_job_with_allocation_
    retry — RunPod's own availability for any single endpoint/GPU tier has
    proven volatile within a single session (confirmed live multiple times
    this project). max_retries/backoff_seconds default from
    RUNPOD_IMAGE_ALLOCATION_MAX_RETRIES/RUNPOD_IMAGE_ALLOCATION_BACKOFF_
    SECONDS when not passed explicitly."""
    if max_retries is None:
        max_retries = int(os.getenv("RUNPOD_IMAGE_ALLOCATION_MAX_RETRIES", str(_DEFAULT_ALLOCATION_MAX_RETRIES)))
    if backoff_seconds is None:
        backoff_seconds = float(os.getenv("RUNPOD_IMAGE_ALLOCATION_BACKOFF_SECONDS", str(_DEFAULT_ALLOCATION_BACKOFF_SECONDS)))

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return run_edit_job(
                endpoint_id, workflow_json, reference_image_bytes, reference_image_filename,
                timeout_seconds=timeout_seconds, poll_interval=poll_interval,
            )
        except (RunPodImageServerlessError, TimeoutError) as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    "Image Serverless allocation attempt %d/%d failed for endpoint %s: %s — retrying in %ss",
                    attempt + 1, max_retries + 1, endpoint_id, exc, backoff_seconds,
                )
                time.sleep(backoff_seconds)

    raise RunPodImageServerlessError(
        f"Image Serverless endpoint {endpoint_id} failed to allocate a worker after {max_retries + 1} attempt(s): {last_exc}"
    ) from last_exc


def unique_reference_filename(extension: str = "png") -> str:
    """A collision-safe filename for the uploaded reference image — the
    job's LoadImage node reads this exact name back, so it needs to be
    unique per call, not content-addressed."""
    return f"culturix-ref-{_uuid.uuid4().hex[:12]}.{extension}"
