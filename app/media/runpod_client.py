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
    mounting the shared Network Volume, fully deleted (not just stopped)
    when training finishes — see that module's docstring.

RunPod's Pods management surface is a GraphQL API at
https://api.runpod.io/graphql, not plain REST — verify this against RunPod's
current docs when setting up credentials, since it hasn't been exercised
against a live account here.

Requires env vars:
  RUNPOD_API_KEY            (RunPod console -> Settings -> API Keys)
  RUNPOD_POD_ID             (manual-testing pod only — see above)
  RUNPOD_TRAINING_GPU_TYPE_ID  (training pod only, e.g. "NVIDIA A100 80GB PCIe")
  RUNPOD_TRAINING_IMAGE        (training pod only — a container image with
                                 ltx-trainer installed)
  RUNPOD_NETWORK_VOLUME_ID     (training pod only — the shared volume to mount)
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


def create_training_pod() -> str:
    """Creates a fresh, ephemeral training pod (A100/H100-class — LTX-2's
    training path needs bf16/more VRAM than the 4090-class inference tier
    comfortably provides), mounting the shared Network Volume so
    ltx-trainer's output lands where the Serverless inference endpoint can
    read it directly. Returns the new pod's id. Caller (culturetoon_lora.py)
    is responsible for terminate_pod()-ing it when done, success or
    failure — this is meant to exist only for the duration of one training
    run, not as standing infrastructure."""
    gpu_type_id = os.getenv("RUNPOD_TRAINING_GPU_TYPE_ID", "")
    image_name = os.getenv("RUNPOD_TRAINING_IMAGE", "")
    volume_id = os.getenv("RUNPOD_NETWORK_VOLUME_ID", "")
    if not gpu_type_id or not image_name or not volume_id:
        raise RuntimeError(
            "RUNPOD_TRAINING_GPU_TYPE_ID, RUNPOD_TRAINING_IMAGE, and RUNPOD_NETWORK_VOLUME_ID must all be set"
        )
    data = _graphql(
        """mutation deployPod($input: PodFindAndDeployOnDemandInput!) {
            podFindAndDeployOnDemand(input: $input) { id desiredStatus }
        }""",
        {"input": {
            "cloudType": "SECURE",
            "gpuTypeId": gpu_type_id,
            "imageName": image_name,
            "networkVolumeId": volume_id,
            "name": "culturix-lora-training",
            "ports": "22/tcp",
        }},
    )
    pod = data.get("podFindAndDeployOnDemand")
    if not pod or not pod.get("id"):
        raise RunPodError(f"RunPod did not return a new pod id: {data}")
    logger.info("Training pod %s created", pod["id"])
    return pod["id"]


def wait_for_ssh_ready(pod_id: str, timeout_seconds: int = 180) -> tuple:
    """Same RUNNING-status wait as wait_for_pod_ready, but returns SSH
    connection info instead of a ComfyUI URL — a training pod doesn't run
    ComfyUI's HTTP server, just needs to be reachable over SSH to run
    ltx-trainer."""
    deadline = time.time() + timeout_seconds
    _wait_until_running(pod_id, deadline)
    return get_pod_ssh_info(pod_id)


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
