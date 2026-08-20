"""Self-hosted (RunPod Serverless + ComfyUI + Qwen-Image-Edit) image
provider — grounds image-to-image generation (character expressions,
variant portraits with a reference photo) on a cheap self-hosted GPU
instead of paid Qwen-Image (DashScope). This is specifically an EDITING
model (preserve the subject, change one thing), not a general
text-to-image model — see app/media/qwen_image_workflow.py's header
comment for why a reference image is required, not optional, here.

Registered ahead of QwenImageProvider in HybridImageProvider's fallback
chain (see that module) since it's the same class of job Cloudflare's
free tier structurally can't do (no image-to-image support) but costs
RunPod GPU-seconds instead of a paid per-call API rate."""
import logging
import os
from typing import Optional

import httpx

from app.media.base import ImageProvider, MediaResult

logger = logging.getLogger("culturix.media.image_selfhosted")

# Placeholder-grade, same posture as app/services/culturetoon_usage.py's
# own cost estimates for the video path — RunPod bills per-second of
# actual worker time, and this hasn't been measured against a real
# deployed endpoint yet. Deliberately conservative (rounds up) rather than
# omitted, so budget tracking has *something* rather than silently
# treating this provider as free.
_ESTIMATED_COST_USD = 0.01


class SelfHostedImageEditError(Exception):
    pass


class SelfHostedImageProvider(ImageProvider):
    def generate(self, prompt: str, reference_image_url: Optional[str] = None) -> MediaResult:
        if not reference_image_url:
            raise SelfHostedImageEditError(
                "SelfHostedImageProvider requires reference_image_url — Qwen-Image-Edit is an "
                "editing model (preserve the subject, change one thing), not a text-to-image model. "
                "Callers with no reference should use a different provider (see HybridImageProvider)."
            )
        endpoint_id = os.getenv("RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID", "")
        if not endpoint_id:
            raise SelfHostedImageEditError("RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID is not configured")

        from app.media import qwen_image_workflow, runpod_serverless_image_client

        ref_resp = httpx.get(reference_image_url, timeout=30)
        ref_resp.raise_for_status()
        reference_bytes = ref_resp.content

        filename = runpod_serverless_image_client.unique_reference_filename()
        workflow = qwen_image_workflow.build_workflow(prompt, filename)

        image_bytes = runpod_serverless_image_client.run_edit_job_with_allocation_retry(
            endpoint_id, workflow, reference_bytes, filename,
        )

        return MediaResult(
            asset_bytes=image_bytes,
            content_type="image/png",
            duration_seconds=None,
            cost_usd=_ESTIMATED_COST_USD,
        )
