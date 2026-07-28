"""Image provider that prefers Cloudflare Workers AI's free tier and falls
back to the paid Qwen-Image provider — the registered "image" provider in
service.py's _PROVIDERS.

Falls back to Qwen-Image when: CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN
aren't set, the free daily Neuron budget is exhausted, the Cloudflare call
fails for any other reason, or a reference_image_url was supplied (FLUX.1
schnell has no image-to-image input, so a reference request skips straight
to Qwen-Image, which does support it — see image_cloudflare.py).

Fail-open by design, matching this codebase's pipeline-node convention: a
free-tier outage must never stop an image from being generated, just make
it cost money again.
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
