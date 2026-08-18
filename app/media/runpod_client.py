"""RunPod pod lifecycle management (start/stop/ready-check) for the
self-hosted (ComfyUI + LTX-2) video generation path — see
app/services/culturetoon_selfhosted_batch.py.

RunPod's Pods management surface is a GraphQL API at
https://api.runpod.io/graphql, not plain REST — verify this against RunPod's
current docs when setting up RUNPOD_API_KEY/RUNPOD_POD_ID, since it hasn't
been exercised against a live account here.

Requires env vars:
  RUNPOD_API_KEY   (RunPod console -> Settings -> API Keys)
  RUNPOD_POD_ID    (the pod to start/stop/SSH into — created once via
                    RunPod console -> Pods -> Templates -> "ComfyUI")
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


def wait_for_pod_ready(pod_id: Optional[str] = None, comfyui_port: int = _DEFAULT_COMFYUI_PORT,
                        timeout_seconds: int = 180) -> str:
    """Polls until the pod is RUNNING, then polls ComfyUI's own /system_stats
    endpoint until it responds — a pod being "running" and ComfyUI being
    ready to accept jobs are different states (ComfyUI's Python process
    still has to boot inside the container). Returns the ComfyUI base URL
    (e.g. "http://1.2.3.4:8188") once ready."""
    pod_id = pod_id or _pod_id()
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        pod = _get_pod_info(pod_id)
        if pod.get("desiredStatus") == "RUNNING":
            break
        time.sleep(_POD_READY_POLL_INTERVAL)
    else:
        raise TimeoutError(f"Pod {pod_id} did not reach RUNNING within {timeout_seconds}s")

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
