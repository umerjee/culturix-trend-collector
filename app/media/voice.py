"""Free voiceover via edge-tts (wraps Microsoft Edge's online TTS — no API key, no cost).

Swapped from ElevenLabs to avoid billing entirely. Note this is an unofficial,
reverse-engineered client for Microsoft's Edge read-aloud service — it has no
SLA/guaranteed uptime and could break if Microsoft changes the underlying
endpoint. Fine for a bootstrapped/free-tier product; if you need guaranteed
reliability at scale later, swap back to a paid provider (e.g. ElevenLabs,
Google Cloud TTS) by restoring an ElevenLabsProvider-style class here and
pointing service.py's _PROVIDERS["voiceover"] at it again.
"""
import asyncio
import io
from typing import Optional
from app.media.base import VoiceProvider, MediaResult

# Natural-sounding neutral English voice. Full voice list: `edge-tts --list-voices`
_DEFAULT_VOICE = "en-US-AriaNeural"


class EdgeTTSProvider(VoiceProvider):
    def synthesize(self, text: str, voice: Optional[str] = None) -> MediaResult:
        try:
            import edge_tts  # noqa: F401  (import check only — used inside _generate)
        except ImportError:
            raise RuntimeError("edge-tts not installed — add 'edge-tts' to requirements.txt")

        voice_id = voice or _DEFAULT_VOICE
        audio_bytes = asyncio.run(_generate(text, voice_id))
        if not audio_bytes:
            raise RuntimeError("edge-tts returned no audio data")

        # ~150 words/min speaking rate; free — no per-call cost
        words = len(text.split())
        return MediaResult(
            asset_bytes=audio_bytes,
            content_type="audio/mpeg",
            duration_seconds=round((words / 150) * 60, 1),
            cost_usd=0.0,
        )


async def _generate(text: str, voice: str) -> bytes:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()
