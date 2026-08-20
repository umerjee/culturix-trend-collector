"""Image provider that prefers Cloudflare Workers AI's free tier (text-only)
or self-hosted RunPod/Qwen-Image-Edit (reference-grounded), falling back to
the paid Qwen-Image (DashScope) provider only if both fail — the
registered "image" provider in service.py's _PROVIDERS.

Three tiers, in order:
  1. Cloudflare Workers AI (free) — text-only, no reference_image_url.
     FLUX.1 schnell has no image-to-image input at all.
  2. Self-hosted RunPod Serverless + Qwen-Image-Edit — used whenever
     reference_image_url IS supplied (this is the entire class of call
     Cloudflare structurally can't do, and every single Expression
     generation is one of these — confirmed live 2026-08-20 that this was
     ALWAYS falling straight to paid Qwen-Image before, unconditionally,
     for every character's every expression). Costs RunPod GPU-seconds
     instead of a paid per-call API rate.
  3. Qwen-Image (DashScope, paid) — final fallback for either tier, and
     the only path when RUNPOD_IMAGE_SERVERLESS_ENDPOINT_ID isn't
     configured at all (e.g. before that endpoint is deployed).

Fail-open by design at every tier, matching this codebase's pipeline-node
convention: a free/cheap-tier outage must never stop an image from being
generated, just make it cost more again.
"""
import logging
from typing import Optional
from app.media.base import ImageProvider, MediaResult

logger = logging.getLogger("culturix.media.image_hybrid")


class HybridImageProvider(ImageProvider):
    def generate(self, prompt: str, reference_image_url: Optional[str] = None) -> MediaResult:
        from app.media.image import QwenImageProvider

        if not reference_image_url:
            try:
                from app.media.image_cloudflare import CloudflareFluxProvider
                return CloudflareFluxProvider().generate(prompt)
            except Exception as e:
                logger.warning(
                    "Cloudflare Workers AI image generation failed, falling back to Qwen-Image: %s", e
                )
            return QwenImageProvider().generate(prompt, reference_image_url=reference_image_url)

        try:
            from app.media.image_selfhosted import SelfHostedImageProvider
            return SelfHostedImageProvider().generate(prompt, reference_image_url=reference_image_url)
        except Exception as e:
            logger.warning(
                "Self-hosted RunPod image editing failed, falling back to paid Qwen-Image: %s", e
            )

        return QwenImageProvider().generate(prompt, reference_image_url=reference_image_url)
