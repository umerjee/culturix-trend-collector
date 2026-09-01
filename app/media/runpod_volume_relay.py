"""Read/write access to a RunPod Network Volume via a short-lived "carrier"
pod, for volumes that don't support RunPod's S3-compatible API.

Why this exists: app/media/runpod_s3.py's whole design assumes every
Network Volume exposes an S3-compatible endpoint (documented at
https://docs.runpod.io/storage/s3-api). Confirmed live 2026-08-31: that's
only true per-datacenter, not universal — EU-RO-1 (RUNPOD_NETWORK_VOLUME_ID,
the training/cache volume) supports it, but EU-NL-1 (RUNPOD_INFERENCE_NETWORK_VOLUME_ID,
a SEPARATE volume actually mounted to the live Serverless inference
endpoint — these are two different env vars pointing at two different
volumes, don't conflate them, see [[project_runpod_volume_mismatch_incident]]
in the memory system) does not (a real EndpointConnectionError against
s3api-eu-nl-1.runpod.io, which doesn't exist). Since a Network Volume can
only otherwise be reached by mounting it to a pod, this module rents a
minimal, short-lived pod with the target volume mounted, does one read or
write over SFTP, and terminates it — the same manual recovery steps used
live to discover and fix a real production bug (every LoRA trained since
2026-08-28 landing only on EU-RO-1, invisible to the EU-NL-1-mounted
inference endpoint) turned into reusable code instead of a one-off fix.

Cost note: unlike an S3 HEAD/GET/PUT (effectively free, sub-second), each
call here rents a real pod for a minute or two. Uses a CPU Pod
(computeType="CPU"), not a GPU one — confirmed live 2026-09-01 via
RunPod's own OpenAPI spec that CPU Pods are a real, separate capacity
pool; an earlier version of this module incorrectly assumed RunPod's
pod-creation API required a GPU type, which meant a pure file-transfer
task was needlessly competing with every real inference/training job for
the same scarce GPU supply (and losing — 5 straight "no instances
available" failures in one session). That's an acceptable, small,
one-time cost per LoRA training run (a handful of these calls against a
run that already costs several dollars in real training GPU-hours) in
exchange for actually landing the file where the inference endpoint can
see it, which S3-to-the-wrong-volume was silently failing to do at all.
"""
import logging
import os
import time

logger = logging.getLogger("culturix.media.runpod_volume_relay")

# This pod does no GPU work at all, it just needs to exist long enough for
# one SFTP hop -- confirmed live 2026-09-01 via RunPod's own OpenAPI spec
# that CPU Pods are a real, separate compute pool (computeType="CPU" +
# cpuFlavorIds), NOT the GPU-only situation this module originally assumed.
# Requesting a GPU for a pure file-transfer task was competing for the
# same scarce 4090/A100/H100-class supply every real inference/training
# job needs, and repeatedly lost (confirmed live 2026-09-01: 5 consecutive
# "no instances currently available" failures across all 11 GPU types
# listed here previously, on both COMMUNITY and SECURE). CPU Pods draw
# from an entirely separate capacity pool with no GPU contention.
_CARRIER_CPU_FLAVOR_IDS = ["cpu3c", "cpu3g", "cpu3m", "cpu5c", "cpu5g", "cpu5m"]
_CARRIER_IMAGE = "runpod/base:1.0.2-ubuntu2204"
_VOLUME_MOUNT_PATH = "/runpod-volume"
_SSH_READY_TIMEOUT_SECONDS = 180


class RunPodVolumeRelayError(Exception):
    pass


def _network_volume_id() -> str:
    volume_id = os.getenv("RUNPOD_NETWORK_VOLUME_ID", "")
    if not volume_id:
        raise RunPodVolumeRelayError("RUNPOD_NETWORK_VOLUME_ID must be set")
    return volume_id


def _create_carrier_pod(cloud_type: str) -> str:
    import httpx
    from app.media.runpod_client import _api_key, _REST_API_BASE, RunPodError

    resp = httpx.post(
        f"{_REST_API_BASE}/pods",
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json={
            "computeType": "CPU",
            "cpuFlavorIds": _CARRIER_CPU_FLAVOR_IDS,
            "cpuFlavorPriority": "availability",
            "vcpuCount": 2,
            "cloudType": cloud_type,
            "imageName": _CARRIER_IMAGE,
            "name": "culturix-volume-relay",
            "ports": ["22/tcp"],
            "containerDiskInGb": 20,
            "networkVolumeId": _network_volume_id(),
            "volumeMountPath": _VOLUME_MOUNT_PATH,
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RunPodError(f"Carrier pod creation failed ({resp.status_code}): {resp.text}")
    pod = resp.json()
    if not pod or not pod.get("id"):
        raise RunPodError(f"RunPod did not return a new carrier pod id: {pod}")
    return pod["id"]


def _rent_carrier_pod():
    """Returns (pod_id, host, port) for a freshly-rented, SSH-ready carrier
    pod with the Network Volume mounted. Tries COMMUNITY first (cheaper),
    falls back to SECURE once if COMMUNITY has no capacity at all — see
    module docstring."""
    from app.media.runpod_client import wait_for_ssh_ready, terminate_pod, RunPodError

    last_exc = None
    for cloud_type in ("COMMUNITY", "SECURE"):
        try:
            pod_id = _create_carrier_pod(cloud_type)
        except RunPodError as exc:
            last_exc = exc
            logger.warning("Carrier pod creation on %s failed: %s", cloud_type, exc)
            continue
        try:
            host, port = wait_for_ssh_ready(pod_id, timeout_seconds=_SSH_READY_TIMEOUT_SECONDS)
            return pod_id, host, port
        except Exception:
            try:
                terminate_pod(pod_id)
            except Exception:
                logger.exception("Failed to terminate carrier pod %s after an SSH-wait failure", pod_id)
            raise
    raise RunPodVolumeRelayError(f"Could not rent a carrier pod on any cloud type: {last_exc}")


def push_file(data: bytes, key: str) -> None:
    """Writes `data` to {volume}/{key} — key is relative to the volume
    root, e.g. "ComfyUI/models/loras/<variant-id>.safetensors", the same
    convention runpod_s3.upload_lora used. Verifies the written file's size
    matches before returning. Always terminates the carrier pod, success
    or failure."""
    from app.media.runpod_client import terminate_pod
    from app.media import runpod_ssh

    pod_id, host, port = _rent_carrier_pod()
    try:
        remote_path = f"{_VOLUME_MOUNT_PATH}/{key}"
        parent_dir = remote_path.rsplit("/", 1)[0]
        exit_code, _out, err = runpod_ssh.run_remote_command(host, port, f"mkdir -p '{parent_dir}'", timeout_seconds=30)
        if exit_code != 0:
            raise RunPodVolumeRelayError(f"Failed to create {parent_dir} on the Network Volume: {err[-1000:]}")

        runpod_ssh.upload_file(host, port, remote_path, data, timeout_seconds=600)

        exit_code, out, err = runpod_ssh.run_remote_command(host, port, f"stat -c%s '{remote_path}'", timeout_seconds=30)
        if exit_code != 0 or (out or "").strip() != str(len(data)):
            raise RunPodVolumeRelayError(
                f"Uploaded {key} but size check failed (expected {len(data)}, got {(out or '').strip() or err[-500:]})"
            )
        logger.info("Pushed %s (%d bytes) to the Network Volume via carrier pod %s", key, len(data), pod_id)
    finally:
        try:
            terminate_pod(pod_id)
        except Exception:
            logger.exception("Failed to terminate carrier pod %s — check the RunPod console manually", pod_id)


def fetch_file(key: str):
    """Returns bytes for {volume}/{key}, or None if the file doesn't exist
    on the volume — combines the old S3 HEAD-then-GET into one carrier-pod
    rental instead of two, since each rental has a real cost unlike a free
    S3 HEAD. Always terminates the carrier pod."""
    from app.media.runpod_client import terminate_pod
    from app.media import runpod_ssh

    pod_id, host, port = _rent_carrier_pod()
    try:
        remote_path = f"{_VOLUME_MOUNT_PATH}/{key}"
        exit_code, _out, _err = runpod_ssh.run_remote_command(host, port, f"test -f '{remote_path}'", timeout_seconds=30)
        if exit_code != 0:
            return None
        return runpod_ssh.download_file(host, port, remote_path, timeout_seconds=1200)
    finally:
        try:
            terminate_pod(pod_id)
        except Exception:
            logger.exception("Failed to terminate carrier pod %s — check the RunPod console manually", pod_id)


def verify_exists(key: str) -> bool:
    """Existence-only check, for callers that already have the bytes from
    their own upload step and just need confirmation (mirrors
    runpod_s3.verify_exists's role) rather than a full fetch_file()
    round-trip."""
    from app.media.runpod_client import terminate_pod
    from app.media import runpod_ssh

    pod_id, host, port = _rent_carrier_pod()
    try:
        remote_path = f"{_VOLUME_MOUNT_PATH}/{key}"
        exit_code, _out, _err = runpod_ssh.run_remote_command(host, port, f"test -f '{remote_path}'", timeout_seconds=30)
        return exit_code == 0
    finally:
        try:
            terminate_pod(pod_id)
        except Exception:
            logger.exception("Failed to terminate carrier pod %s — check the RunPod console manually", pod_id)
