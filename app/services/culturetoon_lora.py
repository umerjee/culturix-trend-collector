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

ltx-trainer's real CLI (confirmed against Lightricks/LTX-2's own docs,
2026-08-18 — this replaces an earlier version of this file that guessed at
a single `python -m ltx_trainer.train --images_dir ... --output ...`
invocation, which is NOT the real interface) is two stages:

  1. `python scripts/process_dataset.py dataset.json --resolution-buckets
     <WxHxF> --model-path <checkpoint> --text-encoder-path <gemma dir>`
     — dataset.json is a JSON array of `{"caption": ..., "video": <path>}`
     objects (one entry per training clip; `video` is the confirmed field
     name — there is no documented plain-image entry type). Writes
     preprocessed tensors to `.precomputed/` under the working directory.
  2. `python scripts/train.py <config.yaml>` — config-file-driven, not
     flag-driven. Needs (at minimum) `model.model_path`,
     `model.text_encoder_path` (a DIRECTORY, not a single file — LTX-2's
     training path needs the full-precision Gemma checkpoint, not the fp4
     single-file variant this codebase downloads for *inference*, see
     app/media/workflows/README.md), `data.preprocessed_data_root`
     (the `.precomputed/` dir from step 1), `output_dir`, and `lora.rank`/
     `optimization.steps`/`learning_rate`. Trained weights land under
     `<output_dir>/checkpoints/lora_weights_step_NNNNN.safetensors`.

**Two real open questions this module can't resolve from docs alone —
recommend a manual first training run (same posture as the manual Serverless
inference validation) before trusting the automated /train-lora endpoint
against a real character:**

  1. Whether a still image is an acceptable `video` entry, or must be a
     real (even trivially short) video file. This module's pragmatic
     choice below — ffmpeg-loop each uploaded still into a short static
     clip on the training pod — is a common workaround for identity-style
     LoRA training in other video-model trainers, not a confirmed-correct
     answer for ltx-trainer specifically.
  2. The exact checkpoint/text-encoder sources ltx-trainer's `model_path`/
     `text_encoder_path` expect for *training* (as opposed to the
     confirmed fp8 inference checkpoint) — configurable below via
     LTX_TRAINING_CHECKPOINT_REPO/FILE and LTX_TRAINING_TEXT_ENCODER_REPO
     rather than hardcoded, since neither has been live-validated yet.

The training pod does NOT mount the Network Volume (see module docstring
above), so it downloads its own copy of these on every run — real disk/
time cost, on top of GPU-hours, worth watching once real numbers exist."""
import json
import logging
import os

logger = logging.getLogger("culturix.services.culturetoon_lora")

MIN_LORA_TRAINING_IMAGES = 10
_TRAINING_TIMEOUT_SECONDS = 3600  # ~1hr ceiling for one character's LoRA run
_DOWNLOAD_TIMEOUT_SECONDS = 1800  # training pod fetches its own models fresh every run
# Where the LoRA lands on the Network Volume, relative to the volume root —
# same directory ComfyUI's LoraLoaderModelOnly node reads from
# (app/media/ltx_workflow.py).
_VOLUME_LORA_KEY_PREFIX = "ComfyUI/models/loras"
_RESOLUTION_BUCKET = "768x1360x49"  # vertical 9:16, ~2s at 24fps — matches the inference canvas
# UNVERIFIED (see module docstring's open question #2) — override via env
# vars once confirmed against a real training run rather than editing code.
_CHECKPOINT_REPO = os.getenv("LTX_TRAINING_CHECKPOINT_REPO", "Lightricks/LTX-2.3")
_CHECKPOINT_FILE = os.getenv("LTX_TRAINING_CHECKPOINT_FILE", "ltx-2.3-22b-dev.safetensors")
_TEXT_ENCODER_REPO = os.getenv("LTX_TRAINING_TEXT_ENCODER_REPO", "google/gemma-3-12b-it")


class LoraTrainingError(Exception):
    pass


def add_training_images(variant, urls: list) -> None:
    """Appends newly-uploaded image URLs to the variant's training set.
    Caller (the router) owns save_image()/storage.upload() for each file
    and the session commit — this just does the list bookkeeping."""
    variant.lora_training_image_urls = (variant.lora_training_image_urls or []) + list(urls)


def _run(runpod_ssh, host, port, command, timeout_seconds, error_prefix):
    exit_code, _stdout, stderr = runpod_ssh.run_remote_command(host, port, command, timeout_seconds=timeout_seconds)
    if exit_code != 0:
        raise LoraTrainingError(f"{error_prefix}: {stderr[-2000:]}")


def train_character_lora(variant) -> None:
    """Synchronous end-to-end training run: creates a fresh ephemeral
    training pod, downloads that pod's own copy of the training-variant
    checkpoint/text-encoder (it doesn't mount the Network Volume, see
    module docstring), stages the variant's training images and converts
    each into a short static clip (ltx-trainer's dataset format is
    video+caption pairs, not bare stills — see module docstring's open
    question #1), preprocesses + runs ltx-trainer's real two-stage CLI over
    SSH, SFTP-downloads the resulting LoRA back to this process, pushes it
    to the Network Volume via its S3-compatible API, and verifies the
    upload landed before setting lora_path (a bare filename, not a URL)/
    lora_status. Mutates `variant` in place — caller owns the session
    commit, same convention as every other CultureToons service function.
    Raises LoraTrainingError on any failure (also setting
    lora_status="failed" first, so a failed attempt is visible even if the
    caller doesn't handle the exception specially). The training pod is
    always terminated, success or failure — it's ephemeral by design,
    never worth keeping around."""
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
        models_dir = f"{work_dir}/models"
        output_dir = f"{work_dir}/output"
        _run(runpod_ssh, host, port,
             f"mkdir -p {work_dir} {models_dir}/checkpoint {models_dir}/text_encoder {output_dir}",
             120, "Failed to set up the training pod's working directory")

        # This pod's own model copy — the Network Volume isn't mounted here.
        checkpoint_path = f"{models_dir}/checkpoint/{_CHECKPOINT_FILE}"
        _run(runpod_ssh, host, port,
             f"hf download {_CHECKPOINT_REPO} {_CHECKPOINT_FILE} --local-dir {models_dir}/checkpoint",
             _DOWNLOAD_TIMEOUT_SECONDS, "Failed to download the training checkpoint")
        text_encoder_dir = f"{models_dir}/text_encoder"
        _run(runpod_ssh, host, port,
             f"hf download {_TEXT_ENCODER_REPO} --local-dir {text_encoder_dir}",
             _DOWNLOAD_TIMEOUT_SECONDS, "Failed to download the training text encoder")

        # Stage each reference image, then loop it into a short static clip
        # — see module docstring's open question #1 on why.
        clip_entries = []
        for i, url in enumerate(images):
            img_path = f"{work_dir}/img_{i:03d}.png"
            clip_path = f"{work_dir}/clip_{i:03d}.mp4"
            width, height, frames = _RESOLUTION_BUCKET.split("x")
            stage_cmd = (
                f"curl -sL --fail '{url}' -o {img_path} && "
                f"ffmpeg -y -loop 1 -i {img_path} -t 2 -r 24 -pix_fmt yuv420p "
                f"-vf scale={width}:{height} {clip_path}"
            )
            _run(runpod_ssh, host, port, stage_cmd, 120, f"Failed to stage/convert training image {i}")
            clip_entries.append({"caption": variant.name, "video": clip_path})

        dataset_json = json.dumps(clip_entries)
        dataset_path = f"{work_dir}/dataset.json"
        _run(runpod_ssh, host, port,
             f"cat > {dataset_path} << 'CULTURIX_EOF'\n{dataset_json}\nCULTURIX_EOF",
             30, "Failed to write dataset.json on the training pod")

        precomputed_dir = f"{work_dir}/.precomputed"
        preprocess_cmd = (
            f"cd /workspace/LTX-2/packages/ltx-trainer && "
            f"python scripts/process_dataset.py {dataset_path} "
            f"--resolution-buckets '{_RESOLUTION_BUCKET}' "
            f"--model-path {checkpoint_path} --text-encoder-path {text_encoder_dir} "
            f"--output-dir {precomputed_dir}"
        )
        _run(runpod_ssh, host, port, preprocess_cmd, _TRAINING_TIMEOUT_SECONDS, "ltx-trainer dataset preprocessing failed")

        config_yaml = (
            f"seed: 42\n"
            f"output_dir: \"{output_dir}\"\n"
            f"model:\n"
            f"  model_path: \"{checkpoint_path}\"\n"
            f"  text_encoder_path: \"{text_encoder_dir}\"\n"
            f"  training_mode: \"lora\"\n"
            f"lora:\n"
            f"  rank: 32\n"
            f"  alpha: 32\n"
            f"optimization:\n"
            f"  learning_rate: 1e-4\n"
            f"  steps: 1000\n"
            f"  batch_size: 1\n"
            f"data:\n"
            f"  preprocessed_data_root: \"{precomputed_dir}\"\n"
        )
        config_path = f"{work_dir}/config.yaml"
        _run(runpod_ssh, host, port,
             f"cat > {config_path} << 'CULTURIX_EOF'\n{config_yaml}\nCULTURIX_EOF",
             30, "Failed to write training config on the training pod")

        train_cmd = f"cd /workspace/LTX-2/packages/ltx-trainer && python scripts/train.py {config_path}"
        _run(runpod_ssh, host, port, train_cmd, _TRAINING_TIMEOUT_SECONDS, "ltx-trainer training run failed")

        # The final checkpoint's exact step-count suffix isn't known ahead
        # of time — find the highest-numbered one ltx-trainer wrote.
        exit_code, stdout, stderr = runpod_ssh.run_remote_command(
            host, port,
            f"ls -1 {output_dir}/checkpoints/lora_weights_step_*.safetensors 2>/dev/null | sort | tail -n 1",
            timeout_seconds=30,
        )
        local_output_path = (stdout or "").strip()
        if exit_code != 0 or not local_output_path:
            raise LoraTrainingError(f"Could not find a trained LoRA checkpoint under {output_dir}/checkpoints: {stderr[-1000:]}")

        lora_filename = f"{variant.id}.safetensors"
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
