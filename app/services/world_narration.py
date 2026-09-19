"""One narrator voice for a whole World video.

LTX-2.5 generates audio jointly with each segment of video, and a script is cut
into independent segments of about 15 seconds (see culturetoon_selfhosted_video.
_split_shots_into_segments). Nothing ties those segments to a speaker, so the
narrator's voice is not guaranteed to be the same from one segment to the next.

So for a hostless World video the narration is NOT left to the video model:
- each line is synthesised with ONE fixed, named neural voice (edge-tts: free,
  no key, dozens of languages), so the voice is identical throughout by
  construction, and the same voice is available in other languages later;
- shot durations are retimed to fit the spoken line;
- the renderer is told the shots are narrated externally, so LTX generates
  ambient sound only, never a voice;
- the narration is mixed over the finished video at the right offsets.

Narration is prepared BEFORE any GPU is spent, and a failure stops the render
with a clear error. It never falls back to the model's own voice, because that
is the mixed-voices outcome this module exists to prevent.
"""
import asyncio
import logging
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("culturix.services.world_narration")

# One documentary-style neural voice per language. Override the English one with
# WORLD_NARRATOR_VOICE. Names verified against edge-tts' live voice list.
NARRATOR_VOICES = {
    "en": "en-GB-RyanNeural", "fr": "fr-FR-HenriNeural", "es": "es-ES-AlvaroNeural",
    "de": "de-DE-ConradNeural", "it": "it-IT-DiegoNeural", "pt": "pt-BR-AntonioNeural",
    "ar": "ar-SA-HamedNeural", "he": "he-IL-AvriNeural", "hi": "hi-IN-MadhurNeural",
    "ja": "ja-JP-KeitaNeural", "ko": "ko-KR-InJoonNeural", "zh-CN": "zh-CN-YunxiNeural",
    "tr": "tr-TR-AhmetNeural", "ru": "ru-RU-DmitryNeural",
}
# Slightly slower than conversational: measured, LTX's own narration ran at about
# 1.4 words/s, a synthetic voice at its default rate is much faster and reads as rushed.
NARRATION_RATE = "-6%"

LEAD_IN_SECONDS = 0.25     # silence before a shot's line starts
TAIL_SECONDS = 0.6         # room after the line before the cut
MIN_SHOT_SECONDS = 4
MAX_SHOT_SECONDS = 14      # a single line longer than this is rejected, not rushed
AMBIENT_GAIN = 0.3         # the video model's own ambient/sfx track, under the narration


class NarrationError(ValueError):
    """Narration could not be prepared or mixed; the render must not proceed."""


def narrator_voice(language: str = "en") -> str:
    if language == "en" and os.getenv("WORLD_NARRATOR_VOICE"):
        return os.environ["WORLD_NARRATOR_VOICE"]
    voice = NARRATOR_VOICES.get(language)
    if not voice:
        raise NarrationError(f"No narrator voice configured for language {language!r}")
    return voice


@dataclass
class ShotLine:
    shot_index: int          # position in the shots list
    text: str
    audio: bytes             # mp3
    duration: float          # seconds of speech
    start: float = 0.0       # seconds into the (planned) video


@dataclass
class NarrationPlan:
    voice: str
    language: str
    lines: list[ShotLine]
    shots: list[dict]                                  # retimed copies, marked narration="external"
    total_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def render_script(self, script):
        """The script with retimed shots, for the renderer only. The stored script is untouched."""
        return _ScriptView(script, self.shots)

    def mux(self, video_bytes: bytes) -> bytes:
        return mux_narration(video_bytes, self)


class _ScriptView:
    """Delegates every attribute to the real script except `shots`."""

    def __init__(self, script, shots: list[dict]):
        self._script = script
        self.shots = shots

    def __getattr__(self, name):
        return getattr(self._script, name)


def _strip_emoji(text: str) -> str:
    from app.media.voice import _strip_emoji as strip
    return strip(text)


async def _generate(text: str, voice: str, rate: str) -> bytes:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    return bytes(chunks)


def synthesize(text: str, voice: str, rate: str = NARRATION_RATE, attempts: int = 3) -> bytes:
    """mp3 bytes for one line, with a couple of retries (the endpoint is unofficial)."""
    cleaned = _strip_emoji(text)
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            audio = asyncio.run(_generate(cleaned, voice, rate))
            if audio:
                return audio
            last = NarrationError("text-to-speech returned no audio")
        except Exception as exc:  # network / service errors
            last = exc
        logger.warning("Narration synthesis attempt %d/%d failed: %s", attempt + 1, attempts, last)
    raise NarrationError(f"Could not synthesise narration: {last}")


def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    if not shutil.which("ffmpeg"):
        raise NarrationError("ffmpeg is not available")
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True)


def probe_duration(data: bytes, suffix: str = ".mp3") -> float:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        path = f.name
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True)
        return float(out.stdout.strip())
    except (ValueError, OSError) as exc:
        raise NarrationError(f"Could not read narration duration: {exc}") from exc
    finally:
        os.unlink(path)


def retime_shots(shots: list[dict], durations: dict[int, float]) -> tuple[list[dict], list[float]]:
    """Copies of `shots`, each narrated shot resized to fit its spoken line and marked
    narration="external" (the renderer then asks the video model for ambient sound only).
    Returns (shots, planned start second of each shot). Un-narrated shots keep their length."""
    out, starts, clock = [], [], 0.0
    for i, shot in enumerate(shots):
        shot = dict(shot)
        planned = float(shot.get("duration_seconds") or MIN_SHOT_SECONDS)
        if i in durations:
            needed = durations[i] + LEAD_IN_SECONDS + TAIL_SECONDS
            if needed > MAX_SHOT_SECONDS:
                raise NarrationError(
                    f"Shot {shot.get('shot_number', i + 1)}'s line takes {durations[i]:.1f}s to speak, too long "
                    f"for one shot (max {MAX_SHOT_SECONDS - LEAD_IN_SECONDS - TAIL_SECONDS:.1f}s). Shorten the "
                    "line or split the shot.")
            planned = float(min(MAX_SHOT_SECONDS, max(MIN_SHOT_SECONDS, math.ceil(needed))))
            shot["narration"] = "external"
        shot["duration_seconds"] = int(planned)
        starts.append(clock)
        clock += planned
        out.append(shot)
    return out, starts


def prepare_narration(shots: list[dict], language: str = "en", voice: Optional[str] = None,
                      synth=synthesize) -> NarrationPlan:
    """Synthesise every narrated shot with the one voice and retime the shots to fit.
    Raises NarrationError (before any GPU spend) if that cannot be done."""
    voice = voice or narrator_voice(language)
    narrated = [(i, (s.get("dialogue") or "").strip()) for i, s in enumerate(shots)]
    narrated = [(i, text) for i, text in narrated if text]
    if not narrated:
        raise NarrationError("The script has no narration to speak")
    clips = {i: synth(text, voice) for i, text in narrated}
    durations = {i: probe_duration(audio) for i, audio in clips.items()}
    retimed, starts = retime_shots(shots, durations)
    lines = [ShotLine(shot_index=i, text=text, audio=clips[i], duration=durations[i],
                      start=starts[i] + LEAD_IN_SECONDS) for i, text in narrated]
    total = float(sum(s["duration_seconds"] for s in retimed))
    logger.info("Narration prepared: voice=%s, %d line(s), %.1fs of speech over %.1fs of video",
                voice, len(lines), sum(durations.values()), total)
    return NarrationPlan(voice=voice, language=language, lines=lines, shots=retimed, total_seconds=total)


def mux_command(video_path: str, line_paths: list[str], offsets_ms: list[int], out_path: str,
                has_ambient: bool, duration: float) -> list[str]:
    """The ffmpeg argv that mixes the narration lines (at their offsets) over the video,
    keeping the video stream untouched and the video model's own audio quiet underneath."""
    inputs = ["-i", video_path]
    for path in line_paths:
        inputs += ["-i", path]
    parts, mix = [], []
    if has_ambient:
        parts.append(f"[0:a]volume={AMBIENT_GAIN}[amb]")
        mix.append("[amb]")
    for n, offset in enumerate(offsets_ms, start=1):
        parts.append(f"[{n}:a]adelay={offset}|{offset},aresample=48000[n{n}]")
        mix.append(f"[n{n}]")
    parts.append("".join(mix) + f"amix=inputs={len(mix)}:duration=longest:normalize=0,alimiter=limit=0.95[aout]")
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.3f}", out_path]


def _has_audio(path: str) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=codec_type", "-of", "csv=p=0", path], capture_output=True, text=True)
    return "audio" in out.stdout


def mux_narration(video_bytes: bytes, plan: NarrationPlan) -> bytes:
    """The video with the narration mixed in. Offsets are scaled by the ratio of the real
    video length to the planned one, because segments are cross-faded and so the finished
    video is a little shorter than the sum of its shots."""
    with tempfile.TemporaryDirectory() as tmp:
        video = os.path.join(tmp, "video.mp4")
        with open(video, "wb") as f:
            f.write(video_bytes)
        actual = probe_duration(video_bytes, ".mp4")
        scale = min(1.0, actual / plan.total_seconds) if plan.total_seconds else 1.0
        paths, offsets = [], []
        for n, line in enumerate(plan.lines):
            path = os.path.join(tmp, f"line{n}.mp3")
            with open(path, "wb") as f:
                f.write(line.audio)
            paths.append(path)
            offsets.append(int(line.start * scale * 1000))
        out = os.path.join(tmp, "out.mp4")
        cmd = mux_command(video, paths, offsets, out, _has_audio(video), actual)
        if not shutil.which("ffmpeg"):
            raise NarrationError("ffmpeg is not available")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(out):
            raise NarrationError(f"Mixing the narration failed: {result.stderr[-400:]}")
        with open(out, "rb") as f:
            return f.read()
