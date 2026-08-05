"""Text-to-speech for Phase 7 clip generation, via Coqui TTS (self-hosted,
free, no API key). See requirements.txt for why the actively-maintained
"coqui-tts" PyPI fork is installed here instead of the archived "TTS"
package — PyPI's "TTS" has no release supporting Python >=3.12 and this
project runs Python 3.14, so it cannot be installed at all as originally
specified. "coqui-tts" exposes the same `from TTS.api import TTS` surface
and the same model zoo (including tts_models/multilingual/multi-dataset/
xtts_v2), so this module's behavior otherwise matches the original spec.

Runs entirely locally — no API key needed. First call downloads model
weights from Hugging Face (~1-2GB for XTTS v2) into the directory named by
the TTS_HOME env var (defaults to Coqui's own user cache dir) — make sure
the deploy environment has network access to huggingface.co on first boot,
or pre-warm the cache and point TTS_HOME at it.

No GPU is available on this project's Railway deployment (nixpacks build,
no Dockerfile/CUDA), so this always runs on CPU. XTTS v2 on CPU is slow —
expect roughly 20-60s to synthesize a 30-40s script. That's an accepted v1
tradeoff, not a bug. Set CLIP_TTS_MODEL=tts_models/en/vctk/vits for a much
faster (English-only, non-cloning) fallback voice if XTTS's latency becomes
a real problem.
"""
import logging
import os
import re
import threading
import wave

logger = logging.getLogger("culturix.services.clip_audio")

_DEFAULT_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
# XTTS v2 is a multi-speaker cloning model with no single implicit "default"
# voice — it always needs either a speaker_wav reference clip or one of its
# bundled preset speaker names. "Claribel Dervla" is one of the preset
# speakers shipped with the model checkpoint.
_DEFAULT_XTTS_SPEAKER = "Claribel Dervla"
# Only used if CLIP_TTS_MODEL is switched to the vits fallback — a VCTK speaker id.
_DEFAULT_VITS_SPEAKER = "p225"

# XTTS v2 silently truncates (not errors) any single call over ~250 characters
# for English — confirmed live: a punctuation-light ~450-character script
# produced audio ~10s shorter than its word count implied, with only a log
# warning to notice by. Script text routinely exceeds this (the spec targets
# 80-110 words, ~450-600 characters), so every synthesis call is chunked to
# stay safely under the limit and the resulting .wav files are concatenated,
# rather than trusting the LLM's output to contain enough sentence breaks for
# XTTS's own internal splitter to keep each piece under the cap.
_MAX_CHARS_PER_CALL = 220

_model_lock = threading.Lock()
_tts_instance = None


class TTSGenerationError(Exception):
    pass


def _get_tts():
    """Loads the TTS model once and caches it at module level — model load
    (multi-second to ~a minute) is the slow part, so this must not happen
    per-request."""
    global _tts_instance
    if _tts_instance is not None:
        return _tts_instance
    with _model_lock:
        if _tts_instance is not None:
            return _tts_instance
        try:
            # Required for non-interactive model download — without this,
            # Coqui's CPML license prompt blocks on stdin, which has no
            # terminal to answer it in a server process and would hang the
            # request forever.
            os.environ.setdefault("COQUI_TOS_AGREED", "1")
            from TTS.api import TTS
            model_name = os.getenv("CLIP_TTS_MODEL", _DEFAULT_MODEL)
            logger.info("Loading TTS model %s (first run downloads weights, can take a while)...", model_name)
            _tts_instance = TTS(model_name=model_name, progress_bar=False).to("cpu")
        except Exception as exc:
            raise TTSGenerationError(f"Failed to load TTS model: {exc}") from exc
    return _tts_instance


def _split_into_chunks(text: str, max_chars: int = _MAX_CHARS_PER_CALL) -> list:
    """Splits on sentence boundaries first, packing consecutive sentences into
    chunks up to max_chars. Falls back to a hard word-boundary split for any
    single "sentence" that alone exceeds max_chars (e.g. punctuation-free
    run-on text, exactly what triggered this in practice)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    chunks = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(sentence) <= max_chars:
            current = sentence
            continue
        words = sentence.split()
        for word in words:
            candidate = f"{current} {word}".strip() if current else word
            if len(candidate) <= max_chars:
                current = candidate
            else:
                chunks.append(current)
                current = word
    if current:
        chunks.append(current)
    return chunks


def _concat_wavs(wav_paths: list, output_path: str) -> None:
    with wave.open(wav_paths[0], "rb") as first:
        params = first.getparams()
    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        for path in wav_paths:
            with wave.open(path, "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


def generate_voiceover(script_text: str, output_path: str) -> str:
    """Synthesizes script_text to a .wav file at output_path. Returns output_path."""
    if not script_text or not script_text.strip():
        raise TTSGenerationError("Cannot synthesize empty script text")

    tts = _get_tts()
    model_name = os.getenv("CLIP_TTS_MODEL", _DEFAULT_MODEL)
    is_xtts = "xtts" in model_name

    try:
        if is_xtts:
            speaker = os.getenv("CLIP_TTS_SPEAKER", _DEFAULT_XTTS_SPEAKER)
            language = os.getenv("CLIP_TTS_LANGUAGE", "en")
            chunks = _split_into_chunks(script_text)

            if len(chunks) == 1:
                tts.tts_to_file(text=chunks[0], file_path=output_path, speaker=speaker, language=language)
            else:
                import tempfile
                with tempfile.TemporaryDirectory() as tmp_dir:
                    part_paths = []
                    for i, chunk in enumerate(chunks):
                        part_path = os.path.join(tmp_dir, f"part_{i}.wav")
                        tts.tts_to_file(text=chunk, file_path=part_path, speaker=speaker, language=language)
                        part_paths.append(part_path)
                    _concat_wavs(part_paths, output_path)
        else:
            kwargs = {"text": script_text, "file_path": output_path}
            if "vctk" in model_name:
                kwargs["speaker"] = os.getenv("CLIP_TTS_SPEAKER", _DEFAULT_VITS_SPEAKER)
            tts.tts_to_file(**kwargs)
    except Exception as exc:
        raise TTSGenerationError(f"TTS synthesis failed: {exc}") from exc

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise TTSGenerationError("TTS produced no audio output")
    return output_path
