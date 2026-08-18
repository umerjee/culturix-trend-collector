"""Per-CharacterVariant LoRA training for the self-hosted (RunPod+ComfyUI+
LTX-2) video path's character-consistency mechanism — see
CharacterVariant.lora_path's docstring and
app/services/culturetoon_selfhosted_video.py. Training itself runs via
ltx-trainer on the RunPod pod, triggered remotely over SSH
(app/media/runpod_ssh.py) — manual-to-*start* (a human calls
POST /variants/{id}/train-lora when they want a new character trained) but
fully automated once started, no separate script to run by hand on the pod.

Exact ltx-trainer CLI flags below are the one piece of this path most
likely to need adjustment after the first real run — verify against
ltx-trainer's own docs/--help once it's installed on the pod."""
import logging
import os

logger = logging.getLogger("culturix.services.culturetoon_lora")

MIN_LORA_TRAINING_IMAGES = 10
_TRAINING_TIMEOUT_SECONDS = 3600  # ~1hr ceiling for one character's LoRA run


class LoraTrainingError(Exception):
    pass


def add_training_images(variant, urls: list) -> None:
    """Appends newly-uploaded image URLs to the variant's training set.
    Caller (the router) owns save_image()/storage.upload() for each file
    and the session commit — this just does the list bookkeeping."""
    variant.lora_training_image_urls = (variant.lora_training_image_urls or []) + list(urls)


def train_character_lora(variant) -> None:
    """Synchronous end-to-end training run: starts the pod (if not already
    running), stages the variant's training images on it, runs
    ltx-trainer over SSH, retrieves the resulting LoRA file via SFTP,
    uploads it to Supabase storage, and sets lora_path/lora_status.
    Mutates `variant` in place — caller owns the session commit, same
    convention as every other CultureToons service function. Raises
    LoraTrainingError on any failure (also setting lora_status="failed"
    first, so a failed attempt is visible even if the caller doesn't
    handle the exception specially)."""
    from app.media import runpod_client, runpod_ssh
    from app.media import storage

    images = variant.lora_training_image_urls or []
    if len(images) < MIN_LORA_TRAINING_IMAGES:
        raise LoraTrainingError(
            f"Need at least {MIN_LORA_TRAINING_IMAGES} training images, have {len(images)}"
        )

    variant.lora_status = "training"
    pod_id = os.getenv("RUNPOD_POD_ID", "")

    try:
        runpod_client.start_pod(pod_id)
        runpod_client.wait_for_pod_ready(pod_id)
        host, port = runpod_client.get_pod_ssh_info(pod_id)

        work_dir = f"/workspace/lora_training/{variant.id}"
        download_cmds = " && ".join(
            f"curl -sL --fail '{url}' -o {work_dir}/img_{i:03d}.png" for i, url in enumerate(images)
        )
        exit_code, _stdout, stderr = runpod_ssh.run_remote_command(
            host, port, f"mkdir -p {work_dir} && {download_cmds}", timeout_seconds=300,
        )
        if exit_code != 0:
            raise LoraTrainingError(f"Failed to stage training images on the pod: {stderr[-2000:]}")

        output_path = f"{work_dir}/output/{variant.id}.safetensors"
        train_cmd = (
            f"cd /workspace/LTX-Video && "
            f"python -m ltx_trainer.train --images_dir {work_dir} --output {output_path} "
            f"--character_name '{variant.name}'"
        )
        exit_code, _stdout, stderr = runpod_ssh.run_remote_command(
            host, port, train_cmd, timeout_seconds=_TRAINING_TIMEOUT_SECONDS,
        )
        if exit_code != 0:
            raise LoraTrainingError(f"ltx-trainer failed: {stderr[-2000:]}")

        lora_bytes = runpod_ssh.download_file(host, port, output_path)
        lora_url = storage.upload(
            lora_bytes, f"culturetoons/loras/{variant.id}.safetensors", "application/octet-stream",
        )
        variant.lora_path = lora_url
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
            runpod_client.stop_pod(pod_id)


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
