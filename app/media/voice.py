"""ElevenLabs TTS provider."""
import os
from typing import Optional
import httpx
from app.media.base import VoiceProvider, MediaResult

# Neutral, clear English voice — swap for any ElevenLabs voice ID
_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel


class ElevenLabsProvider(VoiceProvider):
    def __init__(self) -> None:
        key = os.getenv("ELEVENLABS_API_KEY", "")
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")
        self._key = key
        self._base = "https://api.elevenlabs.io/v1"

    def synthesize(self, text: str, voice: Optional[str] = None) -> MediaResult:
        voice_id = voice or _DEFAULT_VOICE_ID
        resp = httpx.post(
            f"{self._base}/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": self._key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=60,
        )
        resp.raise_for_status()
        # ~150 words/min speaking rate; ~$0.11 per 1 000 chars (Creator plan)
        words = len(text.split())
        return MediaResult(
            asset_bytes=resp.content,
            content_type="audio/mpeg",
            duration_seconds=round((words / 150) * 60, 1),
            cost_usd=round(len(text) * 0.00011, 5),
        )
