# Custom RunPod Serverless worker for CultureToons' self-hosted LTX-2 video
# path. Built on top of the official runpod/worker-comfyui image purely for
# its ComfyUI install/startup scaffolding (comfy-cli, /start.sh, CUDA base,
# the `runpod` Python SDK already wired to exec /handler.py) — NOT for its
# handler.py, which only understands image outputs (see handler.py's own
# header comment) and can't be used as-is for a SaveVideo-terminated
# workflow. We replace /handler.py entirely and layer on the LTXVideo
# custom node plus the two dependency fixes discovered live on RunPod
# 2026-08-18 (kornia/pyramid_blending, comfy_kitchen).
#
# Pin the exact base tag at build time — check
# https://hub.docker.com/r/runpod/worker-comfyui/tags for the current
# latest "-base" variant (clean ComfyUI install, no baked-in model weights,
# since our models live on the Network Volume instead).
FROM runpod/worker-comfyui:5.8.6-base

WORKDIR /comfyui

# Confirmed against RunPod's own docs (docs.runpod.io/serverless/troubleshooting)
# 2026-08-28: this base image's requirements.txt pins runpod~=1.7.12 — squarely
# inside the documented 1.7.11-1.10.0 range that "corrupt[s] per-worker job
# tracking on endpoints that use a network volume... most workers stop
# pulling new jobs," with symptoms of "jobs remain stuck in queue even with
# available workers" and "multiple workers available but jobs funnel to a
# single worker." Matches live behavior exactly: two smoke-test jobs hung
# in IN_PROGRESS for 5-8 minutes on this exact network-volume-attached
# endpoint before being manually cancelled. Fix is upgrade only, no code
# changes needed per RunPod's own docs.
RUN pip install --upgrade "runpod>=1.10.1"

# ffmpeg CLI — not guaranteed present in the base image, which mostly relies
# on PyAV's own bundled/statically-linked ffmpeg libraries for ComfyUI's
# video muxing rather than a system binary. handler.py shells out to the
# `ffmpeg` binary directly (subprocess) to remux SaveVideo's output with
# -movflags +faststart — confirmed live 2026-08-29: without faststart, the
# moov atom lands after the mdat box (ffmpeg/PyAV's default), which several
# real players/preview surfaces either refuse to open or can't start
# playback on without fetching the whole file first. Installed explicitly
# rather than assumed present.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ComfyUI-LTXVideo custom node — same package validated live this session.
RUN git clone --depth 1 https://github.com/Lightricks/ComfyUI-LTXVideo.git custom_nodes/ComfyUI-LTXVideo \
    && pip install -r custom_nodes/ComfyUI-LTXVideo/requirements.txt

# kornia/pyramid_blending fix: ComfyUI-LTXVideo's __init__.py fails to
# import entirely on a stock kornia install (`cannot import name 'pad' from
# kornia.geometry.transform.pyramid`), which takes down EVERY LTXV node
# type, not just blending. This is a genuine kornia/LTXVideo incompatibility
# confirmed live (upgrading kornia does not fix it — 0.8.3 was already
# latest) — Laplacian-pyramid blending isn't needed for basic
# text-to-video, so comment out its import/usage rather than the whole
# extension. Pattern-matched (not fixed line numbers) since upstream lines
# may shift between clones.
RUN sed -i \
    -e '/LTXVLaplacianPyramidBlend/s/^\([^#]\)/# \1/' \
    -e '/pyramid_blending/s/^\([^#]\)/# \1/' \
    custom_nodes/ComfyUI-LTXVideo/__init__.py

# comfy_kitchen: needs to be past the base install for fp8/fp4 model
# support (`cannot import name 'TensorCoreConvRotW4A4Layout'` otherwise).
# Unlike kornia, this one genuinely was just outdated — tested fix:
# 0.2.10 -> 0.2.31.
RUN pip install --upgrade comfy-kitchen

# Extends the base image's extra_model_paths.yaml with text_encoders (see
# that file's own header) so ComfyUI picks up the LTX checkpoint/LoRA/text
# encoder from the attached Network Volume instead of expecting them baked
# into the image.
#
# Paths below are repo-root-relative, not relative to this Dockerfile's own
# folder — RunPod's "deploy from a GitHub repository" build only takes a
# single Dockerfile-path field (no separate build-context field), so it
# builds with the whole repo as context rather than just this directory.
COPY deploy/runpod_serverless/extra_model_paths.yaml /comfyui/extra_model_paths.yaml

# Chatterbox (Resemble AI, MIT-licensed, github.com/resemble-ai/chatterbox) —
# generates narration audio directly on this worker's own GPU instead of
# calling an external TTS API (edge-tts ran on our own backend; ElevenLabs
# is a paid per-call API). Confirmed via real research 2026-08-30: in
# Resemble AI's own blind listening tests Chatterbox Turbo was preferred
# over ElevenLabs 65.3%/24.5%, and it's pip-installable with no separate
# ComfyUI custom node needed — handler.py calls it directly as a plain
# Python library, the same way it already shells out to ffmpeg. Model
# weights are NOT baked into the image (same philosophy as the LTX-2
# checkpoint living on the Network Volume, not the image) — HF_HOME is set
# via the RunPod template's env vars to /runpod-volume/hf_cache so the
# ~2GB download happens once and persists across worker restarts instead
# of re-downloading on every fresh worker.
#
# Confirmed live 2026-08-30: a plain `pip install chatterbox-tts` broke
# ComfyUI's own startup entirely (worker never came up — "ComfyUI did not
# become ready within 120s: Connection refused" on every job, even after
# recycling to a guaranteed-fresh worker) — chatterbox-tts's own dependency
# resolution silently pulled in a different torch/torchvision/torchaudio
# than the CUDA-matched build this base image ships, and pip doesn't warn
# about that kind of "successfully installed something incompatible," it
# only errors on truly unsatisfiable version constraints. Captures the
# base image's exact torch/torchvision/torchaudio pins BEFORE installing
# chatterbox-tts, then force-reinstalls exactly those versions back
# afterward with --no-deps (so their own sub-dependencies aren't pulled
# in again either) — standard mitigation for this exact class of conflict.
#
# Confirmed live 2026-09-01: the 2026-08-30 fix above was INCOMPLETE — it
# only checked that ComfyUI's HTTP server started, not that the GPU
# actually initialized. Every worker was exiting (code 1) on EVERY job
# with `libtorch_cuda.so: undefined symbol: ncclCommResume` — torch's
# compiled extension expecting an NCCL ABI that the installed NCCL package
# didn't provide. Root cause: the original grep only matched lines
# starting with "torch" (torch/torchvision/torchaudio), so it never
# captured or restored the separate `nvidia-nccl-cu12`/`nvidia-cublas-cu12`/
# `nvidia-cudnn-cu12`/etc. CUDA runtime packages torch's wheel depends on —
# chatterbox-tts's own dependency resolution silently changed one of those,
# and --no-deps meant the "restore" step never put it back. Widened the
# pattern to capture the whole CUDA/torch stack, not just torch itself.
RUN pip freeze | grep -iE '^(torch|nvidia-|triton)' > /tmp/pinned-torch.txt \
    && cat /tmp/pinned-torch.txt \
    && pip install chatterbox-tts \
    && pip install --no-deps --force-reinstall -r /tmp/pinned-torch.txt \
    && python -c "import torch; print('torch import OK:', torch.__version__, torch.version.cuda)"
# The above `import torch` is a build-time guard, not a GPU check (no GPU
# is present during a normal Docker build, so torch.cuda.is_available()
# can't be tested here) — but it's enough to catch this exact bug: the
# 2026-09-01 failure was an ImportError raised by `from torch._C import *`
# itself (a plain import, before any .cuda() call), so a broken CUDA/NCCL
# ABI mismatch fails the build immediately instead of only surfacing an
# hour into a real RunPod job.

# Replaces the base image's own /handler.py (image-only outputs) with ours
# (video/gif-aware, matches app/media/runpod_serverless_client.py's
# existing video_base64 contract).
COPY deploy/runpod_serverless/handler.py /handler.py

# CMD is inherited from the base image (/start.sh — launches ComfyUI in the
# background on 127.0.0.1:8188, then execs /handler.py in the foreground).
