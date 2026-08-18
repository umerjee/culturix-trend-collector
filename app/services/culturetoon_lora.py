"""Per-CharacterVariant LoRA training for the self-hosted (RunPod+ComfyUI+
LTX-2) video path's character-consistency mechanism — see
CharacterVariant.lora_path's docstring and
app/services/culturetoon_selfhosted_video.py.

Runs against an EPHEMERAL, on-demand training pod (A100 80GB PCIe — LTX-2's
training path needs bf16/more VRAM than the 4090-class inference tier
comfortably provides), created fresh per run and fully terminated when
done — not a fixed, standing pod.

The training pod does NOT mount the Network Volume — A100 PCIe training
capacity and RTX 4090 inference capacity frequently aren't available in
the same RunPod region (SXM-class cards live in separate NVLink/HGX
chassis from standard PCIe racks, and even PCIe A100 stock doesn't
reliably co-locate with 4090 stock), so there's no guarantee a training
pod can be deployed anywhere the volume is mountable. Instead: ltx-trainer
writes its output to the pod's own local container disk, this module
SFTP-downloads the resulting file back to our backend
(app/media/runpod_ssh.py::download_file), then pushes it to the Network
Volume via its S3-compatible API (app/media/runpod_s3.py) — a network
call, not a filesystem write, so it works regardless of region. Doing the
push from our backend rather than the pod itself also means the S3
credentials never touch the ephemeral, less-trusted remote machine.
lora_path still ends up as a bare filename (not a URL) — see
CharacterVariant.lora_path's docstring — since the file's *final* location
is the volume, this SFTP hop is just how it gets there.

Manual-to-*start* (a human calls POST /variants/{id}/train-lora when they
want a new character trained) but fully automated once started via SSH
(app/media/runpod_ssh.py) — no separate script to run by hand on the pod.

Exact ltx-trainer CLI flags below are the one piece of this path most
likely to need adjustment after the first real run — verify against
ltx-trainer's own docs/--help once it's installed on the training image."""
import logging

logger = logging.getLogger("culturix.services.culturetoon_lora")

MIN_LORA_TRAINING_IMAGES = 10
_TRAINING_TIMEOUT_SECONDS = 3600  # ~1hr ceiling for one character's LoRA run
# Where the LoRA lands on the Network Volume, relative to the volume root —
# same directory ComfyUI's LoraLoader node reads from.
_VOLUME_LORA_KEY_PREFIX = "ComfyUI/models/loras"


class LoraTrainingError(Exception):
    pass


def add_training_images(variant, urls: list) -> None:
    """Appends newly-uploaded image URLs to the variant's training set.
    Caller (the router) owns save_image()/storage.upload() for each file
    and the session commit — this just does the list bookkeeping."""
    variant.lora_training_image_urls = (variant.lora_training_image_urls or []) + list(urls)


def train_character_lora(variant) -> None:
    """Synchronous end-to-end training run: creates a fresh ephemeral
    training pod, stages the variant's training images on it, runs
    ltx-trainer over SSH writing to the pod's own local disk, SFTP-
    downloads the result back to this process, pushes it to the Network
    Volume via its S3-compatible API, and verifies the upload landed
    before setting lora_path (a bare filename, not a URL)/lora_status.
    Mutates `variant` in place — caller owns the session commit, same
    convention as every other CultureToons service function. Raises
    LoraTrainingError on any failure (also setting lora_status="failed"
    first, so a failed attempt is visible even if the caller doesn't
    handle the exception specially). The training pod is always
    terminated, success or failure — it's ephemeral by design, never
    worth keeping around."""
    from app.media import runpod_client, runpod_ssh, runpod_s3

    images = variant.lora_training_image_urls or []
    if len(images) < MIN_LORA_TRAINING_IMAGES:
        raise LoraTrainingError(
            f"Need at least {MIN_LORA_TRAINING_IMAGES} training images, have {len(images)}"
        )

    variant.lora_status = "training"
    pod_id = None

    try:
        pod_id = runpod_client.create_training_pod()
        host, port = runpod_client.wait_for_ssh_ready(pod_id)

        work_dir = f"/workspace/lora_training/{variant.id}"
        download_cmds = " && ".join(
            f"curl -sL --fail '{url}' -o {work_dir}/img_{i:03d}.png" for i, url in enumerate(images)
        )
        exit_code, _stdout, stderr = runpod_ssh.run_remote_command(
            host, port, f"mkdir -p {work_dir} && {download_cmds}", timeout_seconds=300,
        )
        if exit_code != 0:
            raise LoraTrainingError(f"Failed to stage training images on the pod: {stderr[-2000:]}")

        lora_filename = f"{variant.id}.safetensors"
        local_output_path = f"{work_dir}/output/{lora_filename}"
        train_cmd = (
            f"mkdir -p {work_dir}/output && cd /workspace/LTX-Video && "
            f"python -m ltx_trainer.train --images_dir {work_dir} --output {local_output_path} "
            f"--character_name '{variant.name}'"
        )
        exit_code, _stdout, stderr = runpod_ssh.run_remote_command(
            host, port, train_cmd, timeout_seconds=_TRAINING_TIMEOUT_SECONDS,
        )
        if exit_code != 0:
            raise LoraTrainingError(f"ltx-trainer failed: {stderr[-2000:]}")

        lora_bytes = runpod_ssh.download_file(host, port, local_output_path)

        volume_key = f"{_VOLUME_LORA_KEY_PREFIX}/{lora_filename}"
        try:
            runpod_s3.upload_lora(lora_bytes, volume_key)
        except runpod_s3.RunPodS3Error as exc:
            raise LoraTrainingError(str(exc)) from exc
        if not runpod_s3.verify_exists(volume_key):
            raise LoraTrainingError(
                f"Uploaded {volume_key} to the Network Volume but a HEAD check couldn't confirm it landed"
            )

        variant.lora_path = lora_filename
        variant.lora_status = "ready"
        logger.info("LoRA training complete for variant %s", variant.id)
    except LoraTrainingError as exc:
        variant.lora_status = "failed"
        logger.error("LoRA training failed for variant %s: %s", variant.id, exc)
        raise
    except Exception as exc:
        variant.lora_status = "failed"
        logger.exception("LoRA training failed unexpectedly for variant %s", variant.id)
        raise LoraTrainingError(str(exc)) from exc
    finally:
        if pod_id:
            runpod_client.terminate_pod(pod_id)


def run_lora_training(variant_id) -> None:
    """Background-task entry point (POST /variants/{id}/train-lora) — owns
    its own session lifecycle since it runs after the request's own session
    has already closed, same shape as generate_video_for_toon(user_id,
    toon_id) in app/services/culturetoon_video.py."""
    import uuid as _uuid
    from app.db import SessionLocal
    from app.models.character_variant import CharacterVariant

    session = SessionLocal()
    try:
        variant = session.query(CharacterVariant).filter_by(id=_uuid.UUID(str(variant_id))).first()
        if not variant:
            return
        try:
            train_character_lora(variant)
        except LoraTrainingError:
            pass  # already logged + lora_status="failed" set by train_character_lora
        session.commit()
    finally:
        session.close()
