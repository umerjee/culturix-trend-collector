"""Image generation via OpenAI's gpt-image-1 — required so posts can ship
with a visual, not just voiceover/music/video (short-form platforms don't
accept audio-only or caption-only posts).

Originally targeted dall-e-3, but that model has been retired from the
Images API on this account (`client.models.list()` no longer lists it —
only the gpt-image-* family remains, and gpt-image models reject the old
`response_format` param entirely since b64_json is their only output mode)."""
import base64
from app.media.base import ImageProvider, MediaResult

_MODEL = "gpt-image-1"
_SIZE = "1024x1024"
# medium quality, 1024x1024 — ~1056 output image tokens per generation at
# gpt-image-1's published per-image-token rate.
_COST_USD = 0.042


class GptImageProvider(ImageProvider):
    def generate(self, prompt: str) -> MediaResult:
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package not installed — add 'openai' to requirements.txt")

        import os
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        client = OpenAI(api_key=api_key)
        response = client.images.generate(
            model=_MODEL,
            prompt=prompt[:4000],
            size=_SIZE,
            quality="medium",
            n=1,
        )
        b64 = response.data[0].b64_json
        if not b64:
            raise RuntimeError("Image generation returned no image data")

        return MediaResult(
            asset_bytes=base64.b64decode(b64),
            content_type="image/png",
            duration_seconds=None,
            cost_usd=_COST_USD,
        )
