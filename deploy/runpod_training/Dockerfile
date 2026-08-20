# RUNPOD_TRAINING_IMAGE — the ephemeral on-demand training pod
# app/media/runpod_client.py::create_training_pod() deploys per LoRA run
# (app/services/culturetoon_lora.py::train_character_lora). Unlike
# deploy/runpod_serverless/ (a Serverless *endpoint*, no direct SSH), this
# is a regular RunPod Pod that app/media/runpod_ssh.py connects to as
# root@<pod-ip>:<proxied-port> to drive ltx-trainer's two-stage CLI by
# hand — see that module's docstring for the exact commands this image
# needs to support.
#
# Base: runpod/pytorch, not runpod/worker-comfyui (that one's for the
# Serverless/ComfyUI side) — RunPod's own PyTorch template image, chosen
# specifically because RunPod Pods deployed from it get SSH access wired
# automatically (the account's public key, added via RunPod console ->
# Settings -> SSH Public Keys, gets injected as PUBLIC_KEY and written to
# ~/.ssh/authorized_keys by the image's own startup script, which also
# starts sshd) — nothing in this Dockerfile configures SSH itself, it's
# inherited from this base. A "devel" (not "runtime") CUDA variant is used
# since ltx-trainer's preprocessing/training may need the CUDA toolchain,
# not just the runtime libraries.
#
# Pin the exact tag at build time — check
# https://hub.docker.com/r/runpod/pytorch/tags for the current release;
# 2.4.0-py3.11-cuda12.4.1 was current as of this file being written.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /workspace

# ffmpeg: train_character_lora() loops each training image into a short
# static clip on this pod (ltx-trainer's dataset format is video+caption
# pairs, not bare stills — see culturetoon_lora.py's module docstring,
# open question #1). curl: fetches each training image from our storage.
# git: clones LTX-2 below. Most RunPod PyTorch images already have git;
# installed explicitly anyway so this Dockerfile doesn't silently depend
# on that.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl git \
    && rm -rf /var/lib/apt/lists/*

# huggingface_hub's CLI ships the `hf` command (not the older
# `huggingface-cli` name) from ~0.24 onward — train_character_lora()
# literally shells out to `hf download ...` on this pod, so this version
# floor matters, not just "some huggingface_hub version."
RUN pip install --no-cache-dir -U "huggingface_hub[cli]>=0.24"

# Lightricks/LTX-2 — contains packages/ltx-trainer/scripts/
# {process_dataset.py,train.py}, the two-stage CLI train_character_lora()
# runs (confirmed against Lightricks' own docs, 2026-08-18 — see
# culturetoon_lora.py's module docstring). Shallow clone: only the training
# code is needed here, not full history.
RUN git clone --depth 1 https://github.com/Lightricks/LTX-2.git /workspace/LTX-2

# Confirmed live 2026-08-20: the requirements.txt-only approach that used
# to be here left ltx_trainer itself unimportable at all (process_dataset.py
# failed on `import typer` before ever reaching `from ltx_trainer import
# logger`) — plain pip install -r never actually installs the ltx_trainer/
# ltx-core packages themselves, just loose dependencies.
#
# This repo is a uv workspace (root pyproject.toml: [tool.uv.workspace]
# members = ["packages/*"]) — the "correct" install is `uv sync`, but that
# pulls torch>=2.6.0 / torchcodec from a custom cu132 wheel index, which
# would fight this base image's already-working torch 2.4.0/CUDA 12.4.1
# stack (their own pyproject.toml comment even flags a real
# CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH history from exactly this kind
# of cuDNN/torch version drift). Deliberately NOT doing that here — instead:
#   1. Register ltx-core and ltx-trainer as importable local packages
#      (--no-deps: skip pyproject.toml's strict/custom-indexed pins
#      entirely, keep using whatever torch/torchvision this base image
#      already has working).
#   2. Explicitly install ltx-trainer's actual runtime dependencies
#      (from its pyproject.toml `dependencies = [...]` list, confirmed by
#      reading it directly) with no version pins, letting pip pick
#      whatever's compatible with the already-installed torch — EXCLUDING
#      torch/torchvision/torchaudio/torchcodec themselves (version-
#      sensitive, leave the base image's own) and ltx-kernels (an
#      optional compiled-CUDA-extension extra this project doesn't use).
RUN pip install --no-cache-dir --no-deps \
    -e /workspace/LTX-2/packages/ltx-core \
    -e /workspace/LTX-2/packages/ltx-trainer
RUN pip install --no-cache-dir \
    typer rich pyyaml accelerate av "bitsandbytes; sys_platform=='linux'" \
    google-genai imageio imageio-ffmpeg openai opencv-python optimum-quanto \
    pandas peft pillow-heif pydantic safetensors scenedetect \
    sentencepiece soundfile wandb

# Confirmed live 2026-08-20, twice: this base image's own torchaudio
# doesn't match its torch build — `import torchaudio` (pulled in by
# ltx-trainer's decode_latents.py) raised `OSError: undefined symbol:
# _ZNK5torch8autograd4Node4nameEv` loading libtorchaudio.so, the classic
# signature of a torch/torchaudio ABI mismatch, not a missing package.
# First fix attempt placed this reinstall BEFORE the dependency list above
# and it silently got undone — one of those packages' own torch
# requirement made pip's resolver touch torch again, sourced from the
# plain PyPI index (no cu124 suffix), re-desyncing it from the
# already-installed cu124 torchaudio. Placing this LAST guarantees it's
# the final word: explicitly (re)install the matched official trio for
# this exact CUDA pairing — torch 2.4.0 / torchvision 0.19.0 /
# torchaudio 2.4.0 is the PyTorch project's own released cu124 set.
RUN pip install --no-cache-dir \
    torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0 \
    --index-url https://download.pytorch.org/whl/cu124

# No CMD/ENTRYPOINT override — inherited from the base image, which starts
# sshd (see header comment) and otherwise just idles, exactly what an
# SSH-driven ephemeral training pod needs. No baked-in models/weights
# (RUNPOD_TRAINING_CHECKPOINT_REPO/FILE etc. get downloaded fresh per run,
# see train_character_lora — this pod doesn't mount the Network Volume,
# see that function's module docstring on why) and no app code copied in
# either — this image is pure environment, driven entirely over SSH.
