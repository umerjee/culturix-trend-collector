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
#   2. Explicitly install both packages' actual runtime dependencies (from
#      their real pyproject.toml `dependencies = [...]` lists — ltx-trainer's
#      AND ltx-core's, confirmed live 2026-08-20 that skipping ltx-core's own
#      list left `einops`/`scipy`/`transformers` unimportable, since --no-deps
#      above skips a package's own transitive deps too, not just the top-level
#      one) with no version pins except transformers' real upper bound
#      (ltx-core's own pyproject.toml comment: 5.15+ breaks the Gemma 4 text
#      encoder's config attribute access — routes through a heterogeneity
#      layer that raises AmbiguousGlobalPerLayerAttributeError on
#      `config.head_dim`), letting pip pick whatever's otherwise compatible
#      with the already-installed torch — EXCLUDING torch/torchvision/
#      torchaudio/torchcodec themselves (version-sensitive, pinned separately
#      below) and ltx-kernels/mps-sdpa/natten (optional compiled-extension
#      extras this project doesn't use).
RUN pip install --no-cache-dir --no-deps \
    -e /workspace/LTX-2/packages/ltx-core \
    -e /workspace/LTX-2/packages/ltx-trainer
RUN pip install --no-cache-dir \
    typer rich pyyaml accelerate av "bitsandbytes; sys_platform=='linux'" \
    google-genai imageio imageio-ffmpeg openai opencv-python optimum-quanto \
    pandas peft pillow-heif pydantic safetensors scenedetect \
    sentencepiece soundfile wandb \
    einops numpy "scipy>=1.14" "transformers>=5.8.0,<5.15"

# Confirmed live 2026-08-20, three times now:
#  1. This base image's own torchaudio doesn't match its torch build —
#     `import torchaudio` raised `OSError: undefined symbol:
#     _ZNK5torch8autograd4Node4nameEv` loading libtorchaudio.so, the
#     classic signature of a torch/torchaudio ABI mismatch.
#  2. Placing the fix for #1 BEFORE the dependency list above got silently
#     undone by pip touching torch again from the plain PyPI index while
#     satisfying one of those packages — moved to LAST so nothing
#     downstream can override it.
#  3. Pinning torch==2.4.0 (matching this base image) was itself wrong:
#     ltx-core's own pyproject.toml requires torch~=2.7, and its real
#     video_vae code uses it — `det_attn_rope.py`'s
#     @torch.library.custom_op-decorated function failed schema inference
#     under 2.4.0 (`infer_schema(func): Parameter x has unsupported type
#     torch.Tensor` — a torch.library API behavior difference between
#     versions, not a missing/misnamed type). cu124's official wheel index
#     only goes up to torch 2.6.0, so this needs cu126 instead — the
#     installed CUDA *runtime* comes bundled in the torch wheel itself
#     (this doesn't need to match the base image's apt-level 12.4.1
#     toolkit, only the actual GPU driver needs to be new enough, which
#     RunPod's fleet is). torch 2.7.1 / torchvision 0.22.1 / torchaudio
#     2.7.1 is the PyTorch project's own released cu126 set.
RUN pip install --no-cache-dir \
    torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
    --index-url https://download.pytorch.org/whl/cu126

# No CMD/ENTRYPOINT override — inherited from the base image, which starts
# sshd (see header comment) and otherwise just idles, exactly what an
# SSH-driven ephemeral training pod needs. No baked-in models/weights
# (RUNPOD_TRAINING_CHECKPOINT_REPO/FILE etc. get downloaded fresh per run,
# see train_character_lora — this pod doesn't mount the Network Volume,
# see that function's module docstring on why) and no app code copied in
# either — this image is pure environment, driven entirely over SSH.
