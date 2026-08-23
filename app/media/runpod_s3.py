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
volume -> S3 API access; endpoint/region pairs are listed at
https://docs.runpod.io/storage/s3-api — one fixed URL per datacenter, e.g.
EU-RO-1 -> https://s3api-eu-ro-1.runpod.io):
  RUNPOD_S3_ACCESS_KEY_ID
  RUNPOD_S3_SECRET_ACCESS_KEY
  RUNPOD_S3_ENDPOINT_URL   (region-specific — matches wherever the volume lives)
  RUNPOD_S3_REGION         (the datacenter ID, e.g. "EU-RO-1" — RunPod's docs
                             pass this as boto3's region_name; omitting it
                             isn't just cosmetic, requests fail without it)
  RUNPOD_S3_BUCKET         (the network volume itself acts as the bucket)
"""
import logging
import os

logger = logging.getLogger("culturix.media.runpod_s3")

_REQUIRED_ENV_VARS = (
    "RUNPOD_S3_ACCESS_KEY_ID", "RUNPOD_S3_SECRET_ACCESS_KEY",
    "RUNPOD_S3_ENDPOINT_URL", "RUNPOD_S3_REGION", "RUNPOD_S3_BUCKET",
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
        region_name=os.environ["RUNPOD_S3_REGION"],
    )


def upload_lora(data: bytes, key: str) -> None:
    """key: the path within the volume, e.g.
    "ComfyUI/models/loras/<variant-id>.safetensors" — same directory
    ComfyUI's LoraLoader node reads from, so nothing further needs to move
    the file once it's here.

    Uses a single PutObject call, capped at 500MB by RunPod's S3-compatible
    API (https://docs.runpod.io/storage/s3-api) — larger files need
    multipart upload instead. A single character's LoRA is expected to be
    well under that, but this isn't enforced here; if ltx-trainer ever
    produces something larger, put_object will just fail with a clear
    error rather than silently truncating."""
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


def presigned_get_url(key: str, expires_in: int = 3600) -> str:
    """A time-limited, read-only signed URL for `key` — lets an untrusted
    ephemeral pod `curl` a large cached file (e.g. a training checkpoint)
    directly, the same way it already curls HuggingFace/storage URLs
    elsewhere in this codebase, without ever putting real S3 credentials
    on that machine. Used to cache large training model files on the
    Network Volume so repeat LoRA training runs don't re-download the
    same ~tens-of-GB checkpoint/text-encoder from HuggingFace every time
    (see culturetoon_lora.py's checkpoint-caching logic)."""
    client = _client()
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": os.environ["RUNPOD_S3_BUCKET"], "Key": key}, ExpiresIn=expires_in,
    )
