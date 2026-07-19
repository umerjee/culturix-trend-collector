"""Instrumental music generation via aimlapi.com — MiniMax Music 2.6.

Suno was deprecated/removed from aimlapi's lineup (their Suno v1/v2 docs now
404) — MiniMax is the current text-to-music model on the same aggregator.
"""
import os
import time
import httpx
from app.media.base import MusicProvider, MediaResult

_URL = "https://api.aimlapi.com/v2/generate/audio"
_MODEL = "minimax/music-2.6"
_POLL_INTERVAL = 15  # seconds — matches aimlapi's documented polling cadence
_MAX_POLLS = 20      # ~5 minutes


class MiniMaxMusicProvider(MusicProvider):
    def __init__(self) -> None:
        # SUNO_API_KEY is really the shared aimlapi.com account key (works
        # across all their models) — kept under this name to avoid another
        # Railway env var change when the underlying provider switched.
        key = os.getenv("SUNO_API_KEY", "")
        if not key:
            raise RuntimeError("SUNO_API_KEY not set")
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def generate(self, mood_prompt: str, duration_seconds: int = 30) -> MediaResult:
        resp = httpx.post(
            _URL,
            headers=self._headers,
            json={
                "model": _MODEL,
                "prompt": mood_prompt,
                "is_instrumental": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        generation_id = data.get("id")
        if not generation_id:
            raise RuntimeError(f"MiniMax music generation returned no id: {data}")
        if data.get("status") == "error":
            raise RuntimeError(f"MiniMax music generation failed: {data}")

        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            poll = httpx.get(
                _URL,
                headers=self._headers,
                params={"generation_id": generation_id},
                timeout=20,
            )
            poll.raise_for_status()
            result = poll.json()
            status = result.get("status", "")

            if status == "completed":
                audio_url = (result.get("audio_file") or {}).get("url", "")
                if not audio_url:
                    raise RuntimeError(f"MiniMax completed with no audio_file.url: {result}")
                audio = httpx.get(audio_url, timeout=60)
                audio.raise_for_status()
                cost = ((result.get("meta") or {}).get("usage") or {}).get("usd_spent")
                return MediaResult(
                    asset_bytes=audio.content,
                    content_type="audio/mpeg",
                    duration_seconds=float(duration_seconds),
                    cost_usd=float(cost) if cost is not None else None,
                )
            if status == "error":
                raise RuntimeError(f"MiniMax music generation failed: {result}")

        raise TimeoutError(f"MiniMax generation {generation_id} did not complete in time")
