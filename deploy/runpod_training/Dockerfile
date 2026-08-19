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

# ltx-trainer's own dependencies. UNVERIFIED which exact requirements
# file(s) the repo ships and whether they fully cover process_dataset.py +
# train.py's needs beyond what the base image's own PyTorch/CUDA stack
# already provides — install whatever requirements.txt exists at either
# the package level or repo root, tolerating either being absent, and
# treat a clean run of both scripts (not just a clean `pip install`) as
# the real confirmation. Flag and fix here if the first real training run
# hits an ImportError this doesn't cover.
RUN (pip install --no-cache-dir -r /workspace/LTX-2/packages/ltx-trainer/requirements.txt 2>/dev/null || true) \
    && (pip install --no-cache-dir -r /workspace/LTX-2/requirements.txt 2>/dev/null || true)

# No CMD/ENTRYPOINT override — inherited from the base image, which starts
# sshd (see header comment) and otherwise just idles, exactly what an
# SSH-driven ephemeral training pod needs. No baked-in models/weights
# (RUNPOD_TRAINING_CHECKPOINT_REPO/FILE etc. get downloaded fresh per run,
# see train_character_lora — this pod doesn't mount the Network Volume,
# see that function's module docstring on why) and no app code copied in
# either — this image is pure environment, driven entirely over SSH.
