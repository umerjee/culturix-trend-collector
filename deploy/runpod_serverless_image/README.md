# CultureToons self-hosted image editing — Serverless endpoint

Builds a RunPod Serverless worker for Qwen-Image-Edit — replaces paid
Qwen-Image (DashScope) for every reference-image-grounded generation
(every Expression, and any variant portrait with its own reference photo)
with a self-hosted GPU call. See `app/media/image_hybrid.py`'s header
comment for the full three-tier fallback story
(Cloudflare free → this → paid Qwen-Image).

Unlike `deploy/runpod_serverless/` (the LTX-2 video worker), this one
needs **no custom handler.py and no custom ComfyUI node package** — see
`Dockerfile`'s own header comment for exactly why (confirmed by reading
both ComfyUI core's and the stock `runpod/worker-comfyui` handler's real
source, not assumed). The only thing this Dockerfile does is fix the base
image's `extra_model_paths.yaml`.

## 1. Populate the volume with the Qwen-Image-Edit model files

Same Network Volume the video worker already uses (`RUNPOD_S3_*` vars,
already set up — see the main `deploy/README.md`). Three files, same
"temporary Pod, no local Docker" pattern already established:

```bash
pip install -U "huggingface_hub[cli]"
MOUNT=/workspace   # confirm via df -h, don't assume
export HF_HUB_DISABLE_XET=1   # confirmed live twice this project: xet's
                               # accelerated transfer path is unreliable
                               # for large HF downloads over SSH

mkdir -p "$MOUNT/ComfyUI/models/diffusion_models" "$MOUNT/ComfyUI/models/text_encoders" "$MOUNT/ComfyUI/models/vae"

hf download Comfy-Org/Qwen-Image-Edit_ComfyUI \
    --include "split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors" \
    --local-dir "$MOUNT/ComfyUI/models/diffusion_models"
mv "$MOUNT/ComfyUI/models/diffusion_models/split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors" \
   "$MOUNT/ComfyUI/models/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors"

hf download Comfy-Org/Qwen-Image_ComfyUI \
    --include "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
    --local-dir "$MOUNT/ComfyUI/models/text_encoders"
mv "$MOUNT/ComfyUI/models/text_encoders/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
   "$MOUNT/ComfyUI/models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"

hf download Comfy-Org/Qwen-Image_ComfyUI \
    --include "split_files/vae/qwen_image_vae.safetensors" \
    --local-dir "$MOUNT/ComfyUI/models/vae"
mv "$MOUNT/ComfyUI/models/vae/split_files/vae/qwen_image_vae.safetensors" \
   "$MOUNT/ComfyUI/models/vae/qwen_image_vae.safetensors"

ls -lh "$MOUNT/ComfyUI/models/diffusion_models" "$MOUNT/ComfyUI/models/text_encoders" "$MOUNT/ComfyUI/models/vae"
```

Expect ~20.4GB (diffusion model), ~9.4GB (text encoder), ~0.25GB (VAE).
Neither file is gated — no `HF_TOKEN` needed for this one, unlike the LTX-2
training text encoder. The diffusion model goes in a **new**
`diffusion_models` folder — a different ComfyUI model category than
`checkpoints` (which the video worker's LTX-2 checkpoint uses) or `unet`.
`extra_model_paths.yaml` (shared with the video worker) now has an explicit
`diffusion_models: models/diffusion_models/` line for this — `UNETLoader`
reads from the `diffusion_models`-registered folder type in current
ComfyUI, and the pre-existing `unet:` mapping does not cover it. Still
worth confirming the dropdown is populated on the first real deploy.

Text encoder and VAE are **shared** with the (currently unused) base
Qwen-Image text-to-image model — hence downloading from
`Comfy-Org/Qwen-Image_ComfyUI`, not the Edit-specific repo, for those two
files.

## 2. Deploy the Serverless endpoint (RunPod console)

Same flow as the video worker's own README, Option A:

RunPod console → **Serverless** → **New Endpoint** → **Deploy from a
GitHub repository** → select this repo → **Dockerfile path**:

```
/deploy/runpod_serverless_image/Dockerfile
```

Then:

- **GPU**: start with a single mid-size tier (e.g. 24GB) and watch for an
  OOM the way the video/training pipeline's Gemma text encoder hit one —
  Qwen-Image-Edit's diffusion model alone is ~20GB on disk in fp8, so a
  24GB card is genuinely tight once the text encoder and VAE are also
  resident; widen to a bigger tier immediately if the first real job OOMs
  rather than assuming 24GB is enough.
- **Network Volume**: attach the same volume from step 1 (same region
  requirement as the video worker).
- **Env vars**: none required.
- Deploy, copy the **Endpoint ID**.

Set `RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID` in Railway to that ID —
`app/media/image_selfhosted.py` reads it directly; no other config needed.

## 3. Validate before trusting HybridImageProvider's live fallback chain

This whole path fails open (see `image_hybrid.py`) — a broken self-hosted
endpoint just falls back to paid Qwen-Image, so a bad deploy won't break
Expression generation, just quietly cost more again. Still worth a real
validation call before assuming it's actually saving anything:

```python
from app.media import qwen_image_workflow, runpod_serverless_image_client
import os

# Any small real PNG/JPEG works as the reference — this doesn't need to be
# a real character portrait for a plumbing check.
with open("test_reference.png", "rb") as f:
    ref_bytes = f.read()

filename = runpod_serverless_image_client.unique_reference_filename()
workflow = qwen_image_workflow.build_workflow("make the character smile warmly", filename)
image_bytes = runpod_serverless_image_client.run_edit_job(
    os.environ["RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID"], workflow, ref_bytes, filename,
    timeout_seconds=300,
)
open("test_output.png", "wb").write(image_bytes)
```

## Open questions to resolve during that first real run

- **GPU sizing** — see step 2's note above; genuinely unconfirmed until a
  real job runs.
- **Cost per call** — `app/media/image_selfhosted.py`'s
  `_ESTIMATED_COST_USD = 0.01` is a placeholder, not a measured number
  (same posture as the video path's own per-second GPU cost estimate).
  Update it once real RunPod billing for a batch of calls is visible.
