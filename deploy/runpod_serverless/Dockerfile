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
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml

# Replaces the base image's own /handler.py (image-only outputs) with ours
# (video/gif-aware, matches app/media/runpod_serverless_client.py's
# existing video_base64 contract).
COPY handler.py /handler.py

# CMD is inherited from the base image (/start.sh — launches ComfyUI in the
# background on 127.0.0.1:8188, then execs /handler.py in the foreground).
