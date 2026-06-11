"""Kling text-to-video provider.

Kling uses JWT auth — requires two env vars:
  KLING_ACCESS_KEY   (from kling.ai/dev → API Keys)
  KLING_SECRET_KEY   (same page)
"""
import os
import time
import httpx
from app.media.base import VideoProvider, MediaResult
from typing import Optional

_BASE = "https://api.klingai.com"
_POLL_INTERVAL = 10   # seconds
_MAX_POLLS = 36       # ~6 minutes max


def _make_jwt(access_key: str, secret_key: str) -> str:
    try:
        import jwt as pyjwt
    except ImportError:
        raise RuntimeError("PyJWT not installed — add 'PyJWT' to requirements.txt")
    now = int(time.time())
    payload = {"iss": access_key, "exp": now + 1800, "nbf": now - 5}
    return pyjwt.encode(payload, secret_key, algorithm="HS256")


class KlingProvider(VideoProvider):
    def __init__(self) -> None:
        self._access_key = os.getenv("KLING_ACCESS_KEY", "")
        self._secret_key = os.getenv("KLING_SECRET_KEY", "")
        if not self._access_key or not self._secret_key:
            raise RuntimeError("KLING_ACCESS_KEY and KLING_SECRET_KEY must be set")

    def _headers(self) -> dict:
        token = _make_jwt(self._access_key, self._secret_key)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def generate(self, prompt: str, duration_seconds: int = 5,
                 aspect_ratio: str = "9:16") -> MediaResult:
        # Step 1 — create task
        resp = httpx.post(
            f"{_BASE}/v1/videos/text2video",
            headers=self._headers(),
            json={
                "model_name": "kling-v1",
                "prompt": prompt,
                "cfg_scale": 0.5,
                "mode": "std",
                "aspect_ratio": aspect_ratio,
                "duration": str(duration_seconds),
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = (data.get("data") or {}).get("task_id") or data.get("task_id")
        if not task_id:
            raise RuntimeError(f"Kling returned no task_id: {data}")

        # Step 2 — poll until complete
        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            poll = httpx.get(
                f"{_BASE}/v1/videos/text2video/{task_id}",
                headers=self._headers(),
                timeout=20,
            )
            poll.raise_for_status()
            pdata = poll.json().get("data") or poll.json()
            status = pdata.get("task_status", "")
            if status == "succeed":
                videos = pdata.get("task_result", {}).get("videos") or []
                if not videos:
                    raise RuntimeError("Kling task succeeded but no videos in response")
                video_url = videos[0].get("url", "")
                video = httpx.get(video_url, timeout=120)
                video.raise_for_status()
                # cost: ~$0.084/sec (std mode)
                return MediaResult(
                    asset_bytes=video.content,
                    content_type="video/mp4",
                    duration_seconds=float(duration_seconds),
                    cost_usd=round(duration_seconds * 0.084, 4),
                )
            if status == "failed":
                raise RuntimeError(f"Kling task failed: {pdata.get('task_status_msg')}")

        raise TimeoutError(f"Kling task {task_id} did not complete in time")
