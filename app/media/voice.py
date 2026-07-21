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
import re
from typing import Optional
from app.media.base import VoiceProvider, MediaResult

# Natural-sounding neutral English voice. Full voice list: `edge-tts --list-voices`
_DEFAULT_VOICE = "en-US-AriaNeural"

# edge-tts narrates emoji aloud by their alt-text description ("fire", "party
# popper", ...) rather than silently skipping them — hooks routinely contain
# emoji (e.g. "...fans buzzing! 🏃🔥"), so without stripping these first the
# voiceover reads that description out loud, which is the reported bug.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U00002600-\U000026FF"  # misc symbols
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A
    "\U0000FE0F"             # variation selector-16
    "\U0000200D"             # zero-width joiner (compound emoji sequences)
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI_PATTERN.sub("", text)).strip()


class EdgeTTSProvider(VoiceProvider):
    def synthesize(self, text: str, voice: Optional[str] = None) -> MediaResult:
        try:
            import edge_tts  # noqa: F401  (import check only — used inside _generate)
        except ImportError:
            raise RuntimeError("edge-tts not installed — add 'edge-tts' to requirements.txt")

        text = _strip_emoji(text)
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
