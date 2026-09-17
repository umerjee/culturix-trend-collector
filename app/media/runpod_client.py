"""RunPod pod lifecycle management for the self-hosted (ComfyUI + LTX-2.5)
video generation path.

Two distinct uses as of the Network-Volume architecture revision:
  - start_pod/stop_pod/wait_for_pod_ready/get_pod_ssh_info: a persistent,
    manually-created pod — no longer used by the automated batch runner
    (see app/media/runpod_serverless_client.py for that), but kept for the
    spec's own manual first-quality-check workflow (a simple on-demand pod
    is enough to confirm the model produces usable output before building
    the Serverless endpoint).
  - wait_for_ssh_ready/terminate_pod: for short-lived, ephemeral pods
    created on demand for a single task and torn down when it's done —
    e.g. the CPU carrier pods app/media/runpod_volume_relay.py rents to
    reach a Network Volume that has no S3-compatible API of its own.
    (Per-character LoRA training used to be another such use — an A100
    training pod created via a since-removed create_training_pod — but
    that whole path was retired along with LoRA training itself.)

RunPod's Pods management surface is a GraphQL API at
https://api.runpod.io/graphql, not plain REST — verify this against RunPod's
current docs when setting up credentials, since it hasn't been exercised
against a live account here.

Requires env vars:
  RUNPOD_API_KEY               (RunPod console -> Settings -> API Keys)
  RUNPOD_POD_ID                (manual-testing pod only — see above)
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
def wait_for_ssh_ready(pod_id: str, timeout_seconds: int = 180) -> tuple:
    """Same RUNNING-status wait as wait_for_pod_ready, but returns SSH
    connection info instead of a ComfyUI URL — for a pod (e.g. a CPU
    carrier pod, see app/media/runpod_volume_relay.py) that doesn't run
    ComfyUI's HTTP server and just needs to be reachable over SSH.

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
    boot-disk) — the right operation for an ephemeral pod (e.g. a CPU
    carrier pod, see app/media/runpod_volume_relay.py) that only ever
    needed to exist for one short-lived task; nothing about it is worth
    keeping once that task is done. Swallow-and-log, same reasoning as
    stop_pod: called from a `finally` block, must never mask a real
    exception already propagating."""
    try:
        _graphql(
            "mutation terminatePod($input: PodTerminateInput!) { podTerminate(input: $input) }",
            {"input": {"podId": pod_id}},
        )
        logger.info("Training pod %s terminated", pod_id)
    except Exception:
        logger.exception("Failed to terminate RunPod training pod %s — check the RunPod console manually", pod_id)


def list_pods() -> list:
    """All on-demand Pods currently on the account (REST GET /pods — same
    endpoint create_training_pod already POSTs to; this module's opening
    docstring calling the REST surface unexercised predates that and is
    stale). Used by app.scheduler.run_runpod_orphan_pod_reaper — added
    2026-09-16 after a manually-created evaluation pod was left running for
    ~5.5 hours (real billed cost) because terminating it depended entirely
    on a human/agent remembering to, with nothing checking independently.
    Each dict includes `lastStartedAt` (ISO string) and `costPerHr`, both
    needed to compute how long a pod has been burning money."""
    resp = httpx.get(f"{_REST_API_BASE}/pods", headers={"Authorization": f"Bearer {_api_key()}"}, timeout=30)
    resp.raise_for_status()
    return resp.json() or []
