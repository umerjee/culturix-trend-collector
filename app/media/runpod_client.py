"""RunPod pod lifecycle management for the self-hosted (ComfyUI + LTX-2)
video generation path.

Two distinct uses as of the Network-Volume architecture revision:
  - start_pod/stop_pod/wait_for_pod_ready/get_pod_ssh_info: a persistent,
    manually-created pod — no longer used by the automated batch runner
    (see app/media/runpod_serverless_client.py for that), but kept for the
    spec's own manual first-quality-check workflow (a simple on-demand pod
    is enough to confirm the model produces usable output before building
    the Serverless endpoint).
  - create_training_pod/wait_for_ssh_ready/terminate_pod: an EPHEMERAL pod
    created fresh per LoRA training run (app/services/culturetoon_lora.py),
    fully deleted (not just stopped) when training finishes. Does NOT mount
    the Network Volume — A100 PCIe training capacity and RTX 4090 inference
    capacity frequently aren't available in the same RunPod region, so the
    trained LoRA is pushed to the volume afterward via its S3-compatible
    API (app/media/runpod_s3.py) instead of a filesystem write. See that
    module and culturetoon_lora.py's docstrings.

RunPod's Pods management surface is a GraphQL API at
https://api.runpod.io/graphql, not plain REST — verify this against RunPod's
current docs when setting up credentials, since it hasn't been exercised
against a live account here.

Requires env vars:
  RUNPOD_API_KEY               (RunPod console -> Settings -> API Keys)
  RUNPOD_POD_ID                (manual-testing pod only — see above)
  RUNPOD_TRAINING_GPU_TYPE_ID  (training pod only — request "A100 80GB PCIe"
                                 specifically, not SXM; PCIe is the more
                                 broadly available form factor)
  RUNPOD_TRAINING_IMAGE        (training pod only — a container image with
                                 ltx-trainer installed)
"""
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger("culturix.media.runpod_client")

_GRAPHQL_URL = "https://api.runpod.io/graphql"
_DEFAULT_COMFYUI_PORT = 8188
_POD_READY_POLL_INTERVAL = 5  # seconds
_COMFYUI_READY_POLL_INTERVAL = 5  # seconds


class RunPodError(Exception):
    pass


def _api_key() -> str:
    key = os.getenv("RUNPOD_API_KEY", "")
    if not key:
        raise RuntimeError("RUNPOD_API_KEY must be set")
    return key


def _pod_id() -> str:
    pod_id = os.getenv("RUNPOD_POD_ID", "")
    if not pod_id:
        raise RuntimeError("RUNPOD_POD_ID must be set")
    return pod_id


def _graphql(query: str, variables: dict) -> dict:
    resp = httpx.post(
        _GRAPHQL_URL,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json={"query": query, "variables": variables},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RunPodError(f"RunPod GraphQL error: {data['errors']}")
    return data["data"]


def start_pod(pod_id: Optional[str] = None) -> None:
    """Resumes a stopped pod. No-op (RunPod itself handles this idempotently)
    if the pod is already running."""
    pod_id = pod_id or _pod_id()
    _graphql(
        "mutation resumePod($input: PodResumeInput!) { podResume(input: $input) { id desiredStatus } }",
        {"input": {"podId": pod_id}},
    )
    logger.info("RunPod pod %s resume requested", pod_id)


def stop_pod(pod_id: Optional[str] = None) -> None:
    """Stops the pod. Called from a `finally` block in the batch runner so a
    hung job can never leave the pod (and its billing) running — swallow and
    log rather than raise, since a failure here shouldn't mask whatever
    exception is already propagating out of the caller's `finally`."""
    pod_id = pod_id or _pod_id()
    try:
        _graphql(
            "mutation stopPod($input: PodStopInput!) { podStop(input: $input) { id desiredStatus } }",
            {"input": {"podId": pod_id}},
        )
        logger.info("RunPod pod %s stop requested", pod_id)
    except Exception:
        logger.exception("Failed to stop RunPod pod %s — check the RunPod console manually", pod_id)


def _get_pod_info(pod_id: str) -> dict:
    data = _graphql(
        """query pod($input: PodFilter!) {
            pod(input: $input) {
                id desiredStatus
                runtime { ports { ip isIpPublic privatePort publicPort type } }
            }
        }""",
        {"input": {"podId": pod_id}},
    )
    pod = data.get("pod")
    if not pod:
        raise RunPodError(f"RunPod returned no data for pod {pod_id}")
    return pod


def get_pod_ssh_info(pod_id: Optional[str] = None) -> tuple:
    """Returns (host, port) for SSH access to the pod, once running — RunPod
    exposes SSH via a proxied public port on its runtime.ports list rather
    than a fixed host:22."""
    pod_id = pod_id or _pod_id()
    pod = _get_pod_info(pod_id)
    ports = ((pod.get("runtime") or {}).get("ports")) or []
    ssh_port = next((p for p in ports if p.get("privatePort") == 22), None)
    if not ssh_port:
        raise RunPodError(f"Pod {pod_id} has no SSH port exposed yet — is it fully running?")
    return ssh_port["ip"], ssh_port["publicPort"]


def _wait_until_running(pod_id: str, deadline: float) -> dict:
    while time.time() < deadline:
        pod = _get_pod_info(pod_id)
        if pod.get("desiredStatus") == "RUNNING":
            return pod
        time.sleep(_POD_READY_POLL_INTERVAL)
    raise TimeoutError(f"Pod {pod_id} did not reach RUNNING within the timeout")


def wait_for_pod_ready(pod_id: Optional[str] = None, comfyui_port: int = _DEFAULT_COMFYUI_PORT,
                        timeout_seconds: int = 180) -> str:
    """Polls until the pod is RUNNING, then polls ComfyUI's own /system_stats
    endpoint until it responds — a pod being "running" and ComfyUI being
    ready to accept jobs are different states (ComfyUI's Python process
    still has to boot inside the container). Returns the ComfyUI base URL
    (e.g. "http://1.2.3.4:8188") once ready. Manual-testing pod only — see
    this module's docstring."""
    pod_id = pod_id or _pod_id()
    deadline = time.time() + timeout_seconds
    pod = _wait_until_running(pod_id, deadline)

    ports = ((pod.get("runtime") or {}).get("ports")) or []
    comfyui_port_info = next((p for p in ports if p.get("privatePort") == comfyui_port), None)
    if not comfyui_port_info:
        raise RunPodError(f"Pod {pod_id} has no port {comfyui_port} exposed — is ComfyUI configured to listen there?")
    comfyui_url = f"http://{comfyui_port_info['ip']}:{comfyui_port_info['publicPort']}"

    while time.time() < deadline:
        try:
            resp = httpx.get(f"{comfyui_url}/system_stats", timeout=10)
            if resp.status_code == 200:
                logger.info("ComfyUI ready at %s", comfyui_url)
                return comfyui_url
        except httpx.HTTPError:
            pass
        time.sleep(_COMFYUI_READY_POLL_INTERVAL)

    raise TimeoutError(f"ComfyUI at {comfyui_url} did not become ready within {timeout_seconds}s")


# Fallback-ordered list of confirmed-valid (fetched live from RunPod's own
# gpuTypes query, 2026-08-20) 80GB+ GPU type ids suitable for LTX-2 LoRA
# training (needs bf16/more VRAM than the 4090-class inference tier
# comfortably provides). Live availability for any single one of these
# turned out to be highly volatile within the same session — A100 80GB
# PCIe on SECURE, then A100 on COMMUNITY, then H100 80GB HBM3 (the console
# calls this "H100 SXM", but RunPod's actual gpuTypeId uses "HBM3" not
# "SXM" — confirmed via the gpuTypes query after a guessed "...SXM" string
# was rejected outright as unknown) all failed with SUPPLY_CONSTRAINT or
# INVALID_INPUT in quick succession, including one the console had just
# shown as having strong stock. A single hardcoded gpuTypeId is fighting a
# moving target; RunPod's REST API instead accepts a priority-ordered list
# and its own gpuTypePriority="availability" picks whichever is actually
# free right now — structurally the right fix instead of guessing again.
_DEFAULT_TRAINING_GPU_TYPE_IDS = [
    "NVIDIA A100 80GB PCIe",
    "NVIDIA A100-SXM4-80GB",
    "NVIDIA H100 PCIe",
    "NVIDIA H100 80GB HBM3",
    "NVIDIA H100 NVL",
]
_REST_API_BASE = "https://rest.runpod.io/v1"


def create_training_pod() -> str:
    """Creates a fresh, ephemeral training pod on whichever GPU type in
    _DEFAULT_TRAINING_GPU_TYPE_IDS (or RUNPOD_TRAINING_GPU_TYPE_ID first,
    if set — kept as an optional override, not a requirement, precisely
    because pinning one exact type proved too fragile against real
    availability swings) RunPod's own availability-priority selection
    finds free right now, via their REST API (not the older GraphQL
    podFindAndDeployOnDemand mutation, which only accepts a single
    gpuTypeId).

    Does NOT mount the Network Volume — training-capacity and
    inference-capacity regions frequently don't overlap, so this pod
    writes ltx-trainer's output to its own local container disk, and the
    resulting file is pushed to the volume afterward via the
    S3-compatible API (app/media/runpod_s3.py) instead of a filesystem
    write. Returns the new pod's id. Caller (culturetoon_lora.py) is
    responsible for terminate_pod()-ing it when done, success or failure —
    this is meant to exist only for the duration of one training run, not
    as standing infrastructure."""
    image_name = os.getenv("RUNPOD_TRAINING_IMAGE", "")
    if not image_name:
        raise RuntimeError("RUNPOD_TRAINING_IMAGE must be set")

    gpu_type_ids = list(_DEFAULT_TRAINING_GPU_TYPE_IDS)
    override = os.getenv("RUNPOD_TRAINING_GPU_TYPE_ID", "")
    if override:
        # Move to front rather than skip-if-present — an explicit override
        # should win the priority order even when it happens to already
        # be one of the defaults.
        if override in gpu_type_ids:
            gpu_type_ids.remove(override)
        gpu_type_ids.insert(0, override)

    resp = httpx.post(
        f"{_REST_API_BASE}/pods",
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json={
            "gpuTypeIds": gpu_type_ids,
            "gpuTypePriority": "availability",
            # COMMUNITY, not SECURE — confirmed live 2026-08-20: SECURE
            # (RunPod's own guaranteed datacenters) hit a real
            # SUPPLY_CONSTRAINT on the very first live attempt. COMMUNITY
            # (third-party host pool) is a broader, generally
            # better-available supply — an easy tradeoff for an ephemeral
            # one-shot training pod.
            "cloudType": "COMMUNITY",
            "imageName": image_name,
            "name": "culturix-lora-training",
            "ports": ["22/tcp"],
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RunPodError(f"RunPod pod creation failed ({resp.status_code}): {resp.text}")
    pod = resp.json()
    if not pod or not pod.get("id"):
        raise RunPodError(f"RunPod did not return a new pod id: {pod}")
    logger.info("Training pod %s created on %s", pod["id"], pod.get("machine", {}).get("gpuDisplayName", "?"))
    return pod["id"]


# Defaults for create_training_pod_with_retry — overridable via
# RUNPOD_TRAINING_ALLOCATION_MAX_RETRIES/_BACKOFF_SECONDS, same knob shape
# as app/media/runpod_serverless_client.py's allocation retry. A training
# run is backgrounded (see culturetoon_lora.py::run_lora_training) with up
# to an hour of budget total, so a more generous backoff than the
# Serverless side's is affordable here.
_DEFAULT_TRAINING_ALLOCATION_MAX_RETRIES = 2
_DEFAULT_TRAINING_ALLOCATION_BACKOFF_SECONDS = 60


def create_training_pod_with_retry(max_retries: int = None, backoff_seconds: float = None) -> str:
    """Wraps create_training_pod with a retry around allocation failures
    (SUPPLY_CONSTRAINT and similar — RunPod couldn't find a matching host
    right now) — confirmed live this is a real, not hypothetical, failure
    mode for A100 80GB PCIe specifically. Plain create_training_pod() has
    no retry of its own; this is the one train_character_lora actually
    calls."""
    if max_retries is None:
        max_retries = int(os.getenv("RUNPOD_TRAINING_ALLOCATION_MAX_RETRIES", str(_DEFAULT_TRAINING_ALLOCATION_MAX_RETRIES)))
    if backoff_seconds is None:
        backoff_seconds = float(os.getenv("RUNPOD_TRAINING_ALLOCATION_BACKOFF_SECONDS", str(_DEFAULT_TRAINING_ALLOCATION_BACKOFF_SECONDS)))

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return create_training_pod()
        except RunPodError as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    "Training pod allocation attempt %d/%d failed: %s — retrying in %ss",
                    attempt + 1, max_retries + 1, exc, backoff_seconds,
                )
                time.sleep(backoff_seconds)

    raise RunPodError(
        f"Training pod failed to allocate after {max_retries + 1} attempt(s): {last_exc}"
    ) from last_exc


def wait_for_ssh_ready(pod_id: str, timeout_seconds: int = 180) -> tuple:
    """Same RUNNING-status wait as wait_for_pod_ready, but returns SSH
    connection info instead of a ComfyUI URL — a training pod doesn't run
    ComfyUI's HTTP server, just needs to be reachable over SSH to run
    ltx-trainer.

    Polls get_pod_ssh_info within the remaining deadline instead of
    checking it once — confirmed live 2026-08-20: a pod can report
    desiredStatus=RUNNING before RunPod's own port-forwarding info has
    populated in runtime.ports, so a single immediate check can raise
    "no SSH port exposed yet" on a pod that becomes reachable moments
    later. This is a timing race, not a broken pod — a single-shot check
    was wrongly treating the two as the same thing."""
    deadline = time.time() + timeout_seconds
    _wait_until_running(pod_id, deadline)
    while True:
        try:
            return get_pod_ssh_info(pod_id)
        except RunPodError:
            if time.time() >= deadline:
                raise
            time.sleep(_POD_READY_POLL_INTERVAL)


def terminate_pod(pod_id: str) -> None:
    """Fully deletes the pod (as opposed to stop_pod's stop-but-keep-the-
    boot-disk) — the right operation for an ephemeral training pod that
    only ever needed to exist for one run; nothing about it is worth
    keeping once training is done, since the actual output (the LoRA file)
    already lives on the persistent Network Volume, not the pod's own
    disk. Swallow-and-log, same reasoning as stop_pod: called from a
    `finally` block, must never mask a real exception already propagating."""
    try:
        _graphql(
            "mutation terminatePod($input: PodTerminateInput!) { podTerminate(input: $input) }",
            {"input": {"podId": pod_id}},
        )
        logger.info("Training pod %s terminated", pod_id)
    except Exception:
        logger.exception("Failed to terminate RunPod training pod %s — check the RunPod console manually", pod_id)
