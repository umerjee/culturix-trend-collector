"""Video assembly for Phase 7 clips — composites a static image (Ken Burns
pan/zoom), the TTS voiceover, and burned-in word-synced captions into a
vertical 1080x1920 MP4 via ffmpeg. Captions are burned in via a generated
.ass subtitle file rather than chained drawtext filters — more reliable for
styled/timed captions, per the original phase spec's own recommendation.

Requires the `ffmpeg` and `ffprobe` binaries on PATH — see nixpacks.toml for
how these get onto Railway's build image. For local dev, install ffmpeg via
your OS package manager (e.g. `choco install ffmpeg`, `apt install ffmpeg`,
`brew install ffmpeg`).
"""
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger("culturix.services.clip_render")

_WIDTH = 1080
_HEIGHT = 1920
_FPS = 25
# Soft target from the spec ("target under 30s") — the script prompt itself
# targets 80-110 words / ~30-45s, so the two targets can conflict on a longer
# script. When they do, this logs a warning but still renders the full
# voiceover rather than hard-truncating mid-sentence, which would ship a
# clip with abruptly cut-off audio.
_SOFT_MAX_DURATION_SECONDS = 30
_CAPTION_CHUNK_SIZE = 3  # words per on-screen caption group


class RenderError(Exception):
    pass


def _require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError(
            "ffmpeg/ffprobe not found on PATH — install ffmpeg "
            "(see nixpacks.toml for the Railway build config)"
        )


def _probe_duration(audio_path: str) -> float:
    try:
        import ffmpeg
        info = ffmpeg.probe(audio_path)
        return float(info["format"]["duration"])
    except Exception as exc:
        raise RenderError(f"Failed to probe audio duration: {exc}") from exc


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    centis = int(round((secs - int(secs)) * 100))
    if centis == 100:
        centis = 0
        secs += 1
    return f"{hours}:{minutes:02d}:{int(secs):02d}.{centis:02d}"


def _build_ass(word_timestamps: list, ass_path: str, duration: float) -> str:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {_WIDTH}",
        f"PlayResY: {_HEIGHT}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,76,&H00FFFFFF,&H00000000,&H00000000,1,1,4,0,2,60,60,220,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for i in range(0, len(word_timestamps), _CAPTION_CHUNK_SIZE):
        chunk = word_timestamps[i:i + _CAPTION_CHUNK_SIZE]
        start = max(0.0, chunk[0]["start"])
        end = min(duration, chunk[-1]["end"])
        if end <= start:
            continue
        text = " ".join(w["word"] for w in chunk).strip().upper().replace("\n", " ")
        if not text:
            continue
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return ass_path


def _escape_for_filter(path: str) -> str:
    """ffmpeg's filtergraph syntax treats ':' as an option separator and
    '\\' as an escape character, both of which appear in Windows absolute
    paths (e.g. C:\\foo\\bar) — this is the escaping ffmpeg's own docs
    recommend for passing a path into the subtitles filter."""
    return path.replace("\\", "/").replace(":", "\\:")


def render_clip(image_path: str, audio_path: str, word_timestamps: list, output_path: str) -> dict:
    """Composites image + audio + word-synced captions into output_path.
    Returns {"video_path": output_path, "duration_seconds": float}."""
    _require_ffmpeg()

    duration = _probe_duration(audio_path)
    if duration <= 0:
        raise RenderError(f"Invalid audio duration probed: {duration}")
    if duration > _SOFT_MAX_DURATION_SECONDS:
        logger.warning(
            "Voiceover duration %.1fs exceeds the %ds soft target — rendering "
            "the full length rather than truncating audio mid-sentence.",
            duration, _SOFT_MAX_DURATION_SECONDS,
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        ass_path = os.path.join(tmp_dir, "captions.ass")
        _build_ass(word_timestamps, ass_path, duration)

        total_frames = max(1, int(duration * _FPS))
        zoompan = (
            f"scale=8000:-1,zoompan=z='min(zoom+0.0008,1.2)':d={total_frames}:"
            f"s={_WIDTH}x{_HEIGHT}:fps={_FPS},format=yuv420p"
        )
        subtitles = f"subtitles='{_escape_for_filter(ass_path)}'"
        vf = f"{zoompan},{subtitles}"

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-i", audio_path,
            "-vf", vf,
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RenderError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-2000:]}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RenderError("ffmpeg produced no video output")

    return {"video_path": output_path, "duration_seconds": duration}
