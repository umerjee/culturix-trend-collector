# Custom RunPod Serverless worker for CultureToons' self-hosted image
# editing path (Qwen-Image-Edit) — see app/media/image_selfhosted.py and
# app/media/runpod_serverless_image_client.py for why this exists: every
# Expression generation is reference-image-grounded, which was always
# falling straight to paid Qwen-Image (DashScope) before, since
# Cloudflare's free tier has no image-to-image support at all.
#
# Unlike deploy/runpod_serverless/ (the LTX-2 VIDEO worker), this one does
# NOT need a custom handler.py or a custom ComfyUI node extension:
#   - Qwen-Image-Edit's nodes (TextEncodeQwenImageEditPlus etc.) are in
#     ComfyUI CORE as of the version this base image tracks — confirmed by
#     reading comfy_extras/nodes_qwen.py directly, 2026-08-20 — no
#     third-party custom_nodes package required.
#   - The stock runpod/worker-comfyui handler.py already collects
#     SaveImage node outputs and returns them as base64 in
#     output.images[].data, and already accepts input.images (base64) to
#     upload a reference photo before running the workflow — confirmed by
#     reading its real source (github.com/runpod-workers/worker-comfyui/
#     handler.py), not assumed. This is the OPPOSITE situation from the
#     video worker, whose stock handler silently drops video outputs.
#
# So the only thing this Dockerfile does is fix the base image's own
# extra_model_paths.yaml, which is missing the ComfyUI/ prefix and the
# text_encoders mapping — same two gaps already found and fixed for the
# video worker (see deploy/runpod_serverless/extra_model_paths.yaml's own
# header comment for the live-confirmed reasoning; reused verbatim here
# since it's a generic ComfyUI model-path mapping, not video-specific).
#
# Pin the exact base tag at build time — check
# https://hub.docker.com/r/runpod/worker-comfyui/tags for the current
# latest "-base" variant. Matches the tag already validated live for the
# video worker (same family, confirmed working).
FROM runpod/worker-comfyui:5.8.6-base

WORKDIR /comfyui

# Reuses the SAME file as the video worker rather than a duplicate copy —
# it's a generic ComfyUI model-path mapping (base_path + a ComfyUI/
# prefix + text_encoders, both confirmed live against this exact Network
# Volume already), not anything LTX-2/video-specific. See that file's own
# header comment for the live-confirmed reasoning.
COPY deploy/runpod_serverless/extra_model_paths.yaml /comfyui/extra_model_paths.yaml

# No handler.py override, no custom_nodes clone — CMD is inherited from
# the base image (/start.sh — launches ComfyUI, then execs the stock
# /handler.py), which is already correct for this path.
