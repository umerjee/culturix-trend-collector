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
app/media/ltx_workflow.py::build_workflow()'s output directly, unchanged.
`output["video_url"]` is kept as a secondary fallback in case a future
version of our handler switches to uploading to storage and returning a
URL instead of inlining base64 (e.g. for very large files) — not currently
emitted by deploy/runpod_serverless/handler.py.

Also supports a multi-shot contract (`input: {"shot_workflows": [...]}`),
added 2026-08-30 so each ToonScript shot gets its own LTX generation
(real camera cuts + correct per-character identity) instead of one
continuous clip — see run_inference_job's own docstring and
app/services/culturetoon_selfhosted_video.py's module docstring for why.
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
# Defaults for run_inference_job_with_allocation_retry — overridable via
# RUNPOD_ALLOCATION_MAX_RETRIES/RUNPOD_ALLOCATION_BACKOFF_SECONDS so the
# retry count/backoff can be tuned once real-world allocation-failure rates
# are known, without a code change (the Network Volume's inference region
# has shown only "medium" RTX 4090 availability, not "high," so this isn't
# a hypothetical case).
_DEFAULT_ALLOCATION_MAX_RETRIES = 1
_DEFAULT_ALLOCATION_BACKOFF_SECONDS = 45


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
    # handler.py reports narration/mux problems as non-fatal fields on a
    # still-"successful" job (video_base64 present) rather than failing the
    # whole job over an audio-only problem — confirmed live 2026-09-01: this
    # function only ever read video_base64, so a real chatterbox_error/
    # narration_mux_error was silently discarded every time, producing a
    # "successful" video with no audio and no visible explanation why. Log
    # loudly rather than restructuring the return type here (every caller
    # currently expects raw bytes back).
    for warning_key in ("chatterbox_error", "narration_mux_error", "faststart_error"):
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


def run_inference_job(endpoint_id: str, workflow_json: dict = None, timeout_seconds: int = 1200,
                       poll_interval: int = _POLL_INTERVAL, reference_image_bytes: bytes = None,
                       narration_audio_bytes: bytes = None,
                       shot_workflows: list = None, shot_reference_images: list = None,
                       shot_chain_from_previous: list = None,
                       narration_text: str = None,
                       stats: dict = None) -> bytes:
    """Submits a ComfyUI workflow to a RunPod Serverless endpoint and blocks
    until it completes. Returns the output video's raw bytes. Raises
    RunPodServerlessError on a FAILED job or an unrecognized output shape,
    TimeoutError if it never reaches a terminal status in time.

    Two mutually exclusive generation shapes:
    - workflow_json (+ optional reference_image_bytes): the original
      single-clip contract.
    - shot_workflows (+ optional parallel shot_reference_images, same
      length/order): one LTX generation PER SHOT — see app/services/
      culturetoon_selfhosted_video.py's module docstring for why. The
      worker (deploy/runpod_serverless/handler.py) submits each shot's
      workflow to ComfyUI in order (reusing the same already-warm model
      across all of them, far cheaper than N separate cold-ish jobs from
      this client) and concatenates the results before muxing/faststart.
    shot_workflows takes precedence when both are given (shouldn't happen
    in practice — app/services/culturetoon_selfhosted_video.py only ever
    builds one shape or the other).

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

    narration_audio_bytes, when given, is base64-encoded and sent the same
    way — the worker muxes it directly onto the finished video with ffmpeg
    (already installed there for the faststart remux) before returning, so
    the caller gets back one already-dubbed file instead of a silent video
    that then needs a separate local mux pass. Moving this step onto the
    worker (rather than app.services.culturetoon_selfhosted_video doing it
    locally after downloading a silent video) is the whole point of
    passing this through — "encode directly via RunPod".

    narration_text, when given INSTEAD of narration_audio_bytes, is sent
    as plain text — the worker synthesizes it itself via Chatterbox
    (Resemble AI, MIT-licensed, confirmed via research 2026-08-30 to beat
    ElevenLabs in blind listening tests) running on its own GPU, at zero
    marginal API cost, before muxing. narration_audio_bytes takes
    precedence when both are given (the ElevenLabs opt-in path still
    synthesizes on this backend, since it needs the caller's own decrypted
    brand credential)."""
    job_input = {}
    if shot_workflows is not None:
        job_input["shot_workflows"] = shot_workflows
        job_input["shot_reference_images_base64"] = [
            base64.b64encode(b).decode("ascii") if b else None for b in (shot_reference_images or [])
        ]
        # Parallel to shot_workflows: True means the worker should anchor
        # that shot on the PREVIOUS shot's last frame instead of the
        # supplied portrait, so consecutive shots share a scene rather
        # than reading as isolated clips. Omitted entirely when not given,
        # so an older worker image just ignores it and behaves as before.
        if shot_chain_from_previous is not None:
            job_input["shot_chain_from_previous"] = list(shot_chain_from_previous)
    else:
        job_input["workflow"] = workflow_json
        if reference_image_bytes is not None:
            job_input["reference_image_base64"] = base64.b64encode(reference_image_bytes).decode("ascii")
    if narration_audio_bytes is not None:
        job_input["narration_audio_base64"] = base64.b64encode(narration_audio_bytes).decode("ascii")
    elif narration_text:
        job_input["narration_text"] = narration_text
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


def cancel_job(endpoint_id: str, job_id: str) -> None:
    """Stops a queued or in-progress Serverless job — confirmed against
    RunPod's own docs (POST /v2/{endpoint_id}/cancel/{job_id}). Used by
    run_inference_job_with_allocation_retry so a timed-out attempt doesn't
    leave its job orphaned in the queue when a fresh one is submitted —
    confirmed live 2026-08-25: without this, a single allocation-retry
    left TWO jobs queued against the same endpoint for one user click,
    since the first job was never told to stop. Best-effort: a failure to
    cancel here shouldn't block moving on to the retry."""
    try:
        resp = httpx.post(f"{_API_BASE}/{endpoint_id}/cancel/{job_id}", headers=_headers(), timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to cancel orphaned Serverless job %s on endpoint %s: %s", job_id, endpoint_id, exc)


def run_inference_job_with_allocation_retry(endpoint_id: str, workflow_json: dict = None, timeout_seconds: int = 1200,
                                             poll_interval: int = _POLL_INTERVAL,
                                             max_retries: int = None, backoff_seconds: float = None,
                                             reference_image_bytes: bytes = None,
                                             narration_audio_bytes: bytes = None,
                                             shot_workflows: list = None, shot_reference_images: list = None,
                                             shot_chain_from_previous: list = None,
                                             narration_text: str = None) -> bytes:
    """Wraps run_inference_job with a retry specifically around allocation
    failures — RunPod couldn't spin up a worker in time, surfaced here as
    either an explicit FAILED status (RunPodServerlessError) or the job
    never reaching a terminal status at all (TimeoutError). Intended for
    use on only the FIRST job submission of a scheduled batch window (see
    app/services/culturetoon_selfhosted_batch.py) — once a worker is warm,
    subsequent jobs in the same window go through run_inference_job
    directly and rely on the batch runner's own existing per-clip error
    handling instead, not this retry.

    max_retries/backoff_seconds default from RUNPOD_ALLOCATION_MAX_RETRIES/
    RUNPOD_ALLOCATION_BACKOFF_SECONDS env vars when not passed explicitly."""
    if max_retries is None:
        max_retries = int(os.getenv("RUNPOD_ALLOCATION_MAX_RETRIES", str(_DEFAULT_ALLOCATION_MAX_RETRIES)))
    if backoff_seconds is None:
        backoff_seconds = float(os.getenv("RUNPOD_ALLOCATION_BACKOFF_SECONDS", str(_DEFAULT_ALLOCATION_BACKOFF_SECONDS)))

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return run_inference_job(
                endpoint_id, workflow_json, timeout_seconds=timeout_seconds, poll_interval=poll_interval,
                reference_image_bytes=reference_image_bytes, narration_audio_bytes=narration_audio_bytes,
                shot_workflows=shot_workflows, shot_reference_images=shot_reference_images,
                shot_chain_from_previous=shot_chain_from_previous,
                narration_text=narration_text,
            )
        except (RunPodServerlessError, TimeoutError) as exc:
            last_exc = exc
            # Confirmed live 2026-08-25: without cancelling here, a single
            # allocation-retry left the ORIGINAL job still queued on
            # RunPod's side (nothing ever told it to stop) while this loop
            # submitted a brand-new one for the same request — two jobs
            # queued against the endpoint for one user click, doubling
            # queue pressure and potential GPU spend if both ever get
            # picked up.
            orphaned_job_id = getattr(exc, "job_id", None)
            if orphaned_job_id:
                cancel_job(endpoint_id, orphaned_job_id)
            if attempt < max_retries:
                logger.warning(
                    "Serverless allocation attempt %d/%d failed for endpoint %s: %s — retrying in %ss",
                    attempt + 1, max_retries + 1, endpoint_id, exc, backoff_seconds,
                )
                time.sleep(backoff_seconds)

    raise RunPodServerlessError(
        f"Serverless endpoint {endpoint_id} failed to allocate a worker after {max_retries + 1} attempt(s): {last_exc}"
    ) from last_exc
