"""Suno music generation via aimlapi.com aggregator."""
import os
import time
import httpx
from app.media.base import MusicProvider, MediaResult

_BASE = "https://api.aimlapi.com/v2/generate/audio/suno-ai"
_POLL_INTERVAL = 8   # seconds between status checks
_MAX_POLLS = 30      # give up after ~4 minutes


class SunoProvider(MusicProvider):
    def __init__(self) -> None:
        key = os.getenv("SUNO_API_KEY", "")
        if not key:
            raise RuntimeError("SUNO_API_KEY not set")
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def generate(self, mood_prompt: str, duration_seconds: int = 30) -> MediaResult:
        # Step 1 — submit generation request
        resp = httpx.post(
            f"{_BASE}/clip",
            headers=self._headers,
            json={
                "prompt": mood_prompt,
                "model": "chirp-v3-5",
                "make_instrumental": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        # Expect { "clips": [{ "id": "...", "status": "..." }, ...] }
        clips = data.get("clips") or []
        if not clips:
            raise RuntimeError(f"Suno returned no clips: {data}")
        clip_id = clips[0].get("id") or clips[0].get("clip_id")
        if not clip_id:
            raise RuntimeError(f"Suno clip has no id: {clips[0]}")

        # Step 2 — poll until complete
        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            poll = httpx.get(
                f"{_BASE}/clip",
                headers=self._headers,
                params={"clip_ids": clip_id, "expand[]": "audio_url"},
                timeout=20,
            )
            poll.raise_for_status()
            result = poll.json()
            clip_data = (result.get("clips") or {})
            if isinstance(clip_data, list):
                clip_data = {c.get("id"): c for c in clip_data}.get(clip_id, {})
            elif isinstance(clip_data, dict):
                clip_data = clip_data.get(clip_id, {})

            status = clip_data.get("status", "")
            if status in ("complete", "streaming"):
                audio_url = clip_data.get("audio_url", "")
                if audio_url:
                    audio = httpx.get(audio_url, timeout=60)
                    audio.raise_for_status()
                    return MediaResult(
                        asset_bytes=audio.content,
                        content_type="audio/mpeg",
                        duration_seconds=float(clip_data.get("duration") or duration_seconds),
                        cost_usd=0.20,
                    )
            if status == "error":
                raise RuntimeError(f"Suno generation failed: {clip_data.get('error')}")

        raise TimeoutError(f"Suno clip {clip_id} did not complete in time")
