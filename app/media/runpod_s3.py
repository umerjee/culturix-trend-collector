"""S3-compatible upload/verify against a RunPod Network Volume — how a
trained LoRA actually lands where the Serverless inference endpoint can
read it.

Why this exists instead of a filesystem write: the training pod
(app/media/runpod_client.py::create_training_pod, A100 PCIe) does NOT mount
the Network Volume — A100 PCIe capacity and RTX 4090 (inference) capacity
frequently aren't available in the same RunPod region, so there's no
guarantee a training pod can even be deployed in the volume's own region.
RunPod's Network Volumes expose an S3-compatible API instead, which works
across regions since it's a network call, not a filesystem mount.

Design choice: the S3 push happens from OUR backend, not from the training
pod itself. app/services/culturetoon_lora.py SSHes into the pod, runs
ltx-trainer (which writes to the pod's own local container disk), then
SFTP-downloads the resulting file back to this process before calling
upload_lora() here — the alternative (running an `aws s3 cp` on the pod
with S3 credentials injected into its environment) would mean a short-lived,
less-trusted remote machine holds those credentials, however briefly.
Keeping the push backend-side avoids that entirely, at the cost of one
extra SFTP hop, which is negligible next to the training job's own runtime.

Requires env vars (RunPod console -> Storage -> Network Volumes -> your
volume -> S3 API access):
  RUNPOD_S3_ACCESS_KEY_ID
  RUNPOD_S3_SECRET_ACCESS_KEY
  RUNPOD_S3_ENDPOINT_URL   (region-specific — matches wherever the volume lives)
  RUNPOD_S3_BUCKET         (the network volume itself acts as the bucket)
"""
import logging
import os

logger = logging.getLogger("culturix.media.runpod_s3")

_REQUIRED_ENV_VARS = (
    "RUNPOD_S3_ACCESS_KEY_ID", "RUNPOD_S3_SECRET_ACCESS_KEY",
    "RUNPOD_S3_ENDPOINT_URL", "RUNPOD_S3_BUCKET",
)


class RunPodS3Error(Exception):
    pass


def _client():
    import boto3

    missing = [var for var in _REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise RuntimeError(f"Missing required env var(s): {', '.join(missing)}")
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ["RUNPOD_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["RUNPOD_S3_SECRET_ACCESS_KEY"],
        endpoint_url=os.environ["RUNPOD_S3_ENDPOINT_URL"],
    )


def upload_lora(data: bytes, key: str) -> None:
    """key: the path within the volume, e.g.
    "ComfyUI/models/loras/<variant-id>.safetensors" — same directory
    ComfyUI's LoraLoader node reads from, so nothing further needs to move
    the file once it's here."""
    client = _client()
    try:
        client.put_object(Bucket=os.environ["RUNPOD_S3_BUCKET"], Key=key, Body=data)
        logger.info("Uploaded %s to the Network Volume", key)
    except Exception as exc:
        raise RunPodS3Error(f"Failed to upload {key} to the Network Volume: {exc}") from exc


def verify_exists(key: str) -> bool:
    """A HEAD-object check — confirms the upload actually landed rather
    than trusting put_object's success response alone, per the spec's own
    "confirms the upload succeeded" requirement."""
    from botocore.exceptions import ClientError

    client = _client()
    try:
        client.head_object(Bucket=os.environ["RUNPOD_S3_BUCKET"], Key=key)
        return True
    except ClientError:
        return False
