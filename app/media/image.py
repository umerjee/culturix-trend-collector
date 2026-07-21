"""Image generation via Alibaba Dashscope's Qwen-Image — required so posts can
ship with a visual, not just voiceover/music/video (short-form platforms don't
accept audio-only or caption-only posts).

Chosen over OpenAI's gpt-image-1 to match this codebase's existing pattern of
Chinese-provider media (MiniMax for music, Kling for video, Qwen for text
content) and to reuse the already-configured QWEN_API_KEY. Dashscope has two
non-interchangeable regional deployments (China: dashscope.aliyuncs.com,
International: dashscope-intl.aliyuncs.com) — this account's key only
authenticates against the international endpoint, confirmed live (same fix
applied in content_strategist.py's Qwen client)."""
import os
import httpx
from app.media.base import ImageProvider, MediaResult

_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
_MODEL = "qwen-image-2.0"
_SIZE = "1024*1024"
# Dashscope bills successfully generated images only; no published fixed
# per-image rate at time of integration — left as None rather than guessing.
_COST_USD = None


class QwenImageProvider(ImageProvider):
    def generate(self, prompt: str) -> MediaResult:
        key = os.environ.get("QWEN_API_KEY")
        if not key:
            raise RuntimeError("QWEN_API_KEY not set")

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {
            "model": _MODEL,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt[:2000]}]}]},
            "parameters": {"size": _SIZE, "n": 1, "watermark": False},
        }
        resp = httpx.post(_URL, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        try:
            image_url = data["output"]["choices"][0]["message"]["content"][0]["image"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Qwen-Image returned no image data: {data}")

        image_resp = httpx.get(image_url, timeout=60)
        image_resp.raise_for_status()

        return MediaResult(
            asset_bytes=image_resp.content,
            content_type="image/png",
            duration_seconds=None,
            cost_usd=_COST_USD,
        )
