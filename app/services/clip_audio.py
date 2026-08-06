"""Text-to-speech for faceless-reel generation, via the same free edge-tts
integration already used for the main product's "voiceover" media type
(app/media/voice.py). This module's original implementation (self-hosted
Coqui XTTS v2, CPU-bound, 20-60s per script, ~1-2GB model download on first
boot) has been dropped entirely in favor of the already-proven, already-live
provider — plus one thing edge-tts gives for free that Coqui never could:
real per-word timestamps.

Confirmed live (not assumed): edge_tts.Communicate's `boundary` parameter
defaults to "SentenceBoundary" — only passing boundary="WordBoundary"
explicitly emits one WordBoundary event per word (offset/duration in
100-nanosecond ticks, converted to seconds below), matching exactly the
{"word", "start", "end"} shape clip_render.py's caption-burning already
expects. This replaces the previously-separate faster-whisper
re-transcription pass (clip_transcribe.py, now removed) entirely — no
second CPU-heavy model, no re-transcribing audio that was already spoken
from known text.
"""
import asyncio
import logging

# Imported directly rather than duplicated (this codebase's usual small-
# helper convention, e.g. culturetoon_clip_cutter.py's _require_ffmpeg) —
# _strip_emoji is a ~15-line unicode-range regex genuinely worth keeping in
# one place rather than risking two copies drifting apart.
from app.media.voice import _DEFAULT_VOICE, _strip_emoji

logger = logging.getLogger("culturix.services.clip_audio")


class TTSGenerationError(Exception):
    pass


async def _synthesize_with_word_timestamps(text: str, voice: str) -> tuple:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    audio_chunks = []
    words = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "word": chunk["text"],
                "start": chunk["offset"] / 1e7,
                "end": (chunk["offset"] + chunk["duration"]) / 1e7,
            })
    return b"".join(audio_chunks), words


def generate_voiceover_with_timestamps(script_text: str, output_path: str, voice: str = None) -> list:
    """Synthesizes script_text to output_path (mp3) and returns real
    per-word timestamps: [{"word", "start", "end"}, ...] in seconds."""
    if not script_text or not script_text.strip():
        raise TTSGenerationError("Cannot synthesize empty script text")

    text = _strip_emoji(script_text)
    voice_id = voice or _DEFAULT_VOICE
    try:
        audio_bytes, words = asyncio.run(_synthesize_with_word_timestamps(text, voice_id))
    except Exception as exc:
        raise TTSGenerationError(f"TTS synthesis failed: {exc}") from exc

    if not audio_bytes:
        raise TTSGenerationError("TTS produced no audio output")
    if not words:
        raise TTSGenerationError("TTS produced no word timestamps")

    with open(output_path, "wb") as f:
        f.write(audio_bytes)
    return words
