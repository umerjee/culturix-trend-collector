"""Word-level timestamp transcription for Phase 7 caption sync, via
faster-whisper. Drives the caption timing in clip_render.py — re-transcribing
the TTS output (rather than trusting speaking-rate estimates) keeps caption
timing accurate even though Coqui TTS doesn't expose its own word-boundary
events the way edge-tts does.
"""
import logging
import os
import threading

logger = logging.getLogger("culturix.services.clip_transcribe")

_model_lock = threading.Lock()
_whisper_model = None


class TranscriptionError(Exception):
    pass


def _get_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _model_lock:
        if _whisper_model is not None:
            return _whisper_model
        try:
            from faster_whisper import WhisperModel
            model_size = os.getenv("CLIP_WHISPER_MODEL", "base")
            logger.info("Loading faster-whisper model %s (first run downloads weights)...", model_size)
            _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        except Exception as exc:
            raise TranscriptionError(f"Failed to load Whisper model: {exc}") from exc
    return _whisper_model


def transcribe_with_timestamps(audio_path: str) -> list[dict]:
    """Returns [{"word": str, "start": float, "end": float}, ...] in order."""
    model = _get_model()
    try:
        segments, _info = model.transcribe(audio_path, word_timestamps=True)
        words = []
        for segment in segments:
            for word in (segment.words or []):
                words.append({"word": word.word.strip(), "start": word.start, "end": word.end})
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

    if not words:
        raise TranscriptionError("Transcription produced no word-level timestamps")
    return words
