"""Cloudflare Workers AI FLUX.1 [schnell] image provider.

Chosen as the primary image provider (see image_hybrid.py) because Workers
AI's free tier — 10,000 Neurons/day, resetting daily with no expiry, no
credit card — comfortably covers Culturix's Pro-tier image quota (50/month
per profile) at zero marginal cost. This is unlike every other option
evaluated: Qwen-Image's new-user quota is a one-time 100-image/90-day
allowance, not sustained; Google's Gemini free tier explicitly excludes use
in "a revenue-generating service" per its own terms, which rules it out for
a Stripe-billed product outright.

Text-to-image only — flux-1-schnell has no image-to-image/reference-image
input, so any request needing a reference photo (see clusterer.py's
_tag_cluster_reference_image) must skip this provider entirely; that's
handled in image_hybrid.py, not here.
"""
import base64
import os
import httpx
from typing import Optional
from app.media.base import ImageProvider, MediaResult

_MODEL = "@cf/black-forest-labs/flux-1-schnell"
_MAX_STEPS = 8  # documented cap; higher improves quality within that ceiling
# Billed in Neurons against the free daily allocation (10,000/day), not USD —
# 0.0 while operating inside that budget. If Cloudflare ever bills overage
# in USD this should be revisited, but there's no published Neuron->USD rate
# at time of integration worth guessing at here.
_COST_USD = 0.0


class CloudflareFluxProvider(ImageProvider):
    def __init__(self) -> None:
        self._account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
        self._token = os.getenv("CLOUDFLARE_API_TOKEN", "")
        if not self._account_id or not self._token:
            raise RuntimeError("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN must be set")

    def generate(self, prompt: str, reference_image_url: Optional[str] = None) -> MediaResult:
        resp = httpx.post(
            f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai/run/{_MODEL}",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            json={"prompt": prompt[:2048], "steps": _MAX_STEPS},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success", True):
            raise RuntimeError(f"Cloudflare Workers AI returned an error: {data.get('errors')}")

        # Cloudflare's own docs show the bare {"image": ...} shape, but the
        # general v4 API envelope wraps results under "result" — accept both
        # rather than betting on one.
        image_b64 = (data.get("result") or {}).get("image") or data.get("image")
        if not image_b64:
            raise RuntimeError(f"Cloudflare Workers AI returned no image data: {data}")

        return MediaResult(
            asset_bytes=base64.b64decode(image_b64),
            content_type="image/jpeg",
            duration_seconds=None,
            cost_usd=_COST_USD,
        )
