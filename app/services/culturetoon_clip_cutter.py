"""Cuts 3-4 shorter candidate clips from one Kling Omni multi-shot video, for
the user to pick from when posting. Not merged into clip_render.py — that
module's scope (Phase 7's clip pipeline) is composing image+TTS+captions
into a video, a different concern from segmenting an already-rendered one.
_require_ffmpeg()/duration-probing are duplicated (not imported) from that
module, matching this codebase's existing precedent of small-helper
duplication over cross-module coupling (see clips.py::_fetch_source /
culturetoons.py::_fetch_trend_source).
"""
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("culturix.services.culturetoon_clip_cutter")

_NUM_CANDIDATE_CLIPS = 4
_CLIP_TARGET_SECONDS = 6


class ClipCutError(Exception):
    pass


def _require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ClipCutError("ffmpeg/ffprobe not found on PATH")


def _probe_duration(video_path: str) -> float:
    try:
        import ffmpeg
        info = ffmpeg.probe(video_path)
        return float(info["format"]["duration"])
    except Exception as exc:
        raise ClipCutError(f"Failed to probe video duration: {exc}") from exc


def _compute_offsets(duration: float, num_clips: int, clip_seconds: int) -> list:
    """Evenly-spaced start offsets across the real source duration — not the
    requested shot durations, since Kling's actual multi-shot output length
    isn't guaranteed to match the prompt DSL to the frame. Each clip is
    clamped so it never runs past the end of the source."""
    if duration <= 0:
        raise ClipCutError(f"Invalid source video duration: {duration}")

    effective_clip_seconds = min(clip_seconds, duration)
    if num_clips <= 1 or duration <= effective_clip_seconds:
        return [0.0]

    max_start = max(0.0, duration - effective_clip_seconds)
    step = max_start / (num_clips - 1)
    return [round(min(i * step, max_start), 2) for i in range(num_clips)]


def cut_clips(source_video_path: str, output_dir: str,
              num_clips: int = _NUM_CANDIDATE_CLIPS, clip_seconds: int = _CLIP_TARGET_SECONDS) -> list:
    """Returns [{"path": str, "start": float, "end": float}, ...]."""
    _require_ffmpeg()
    duration = _probe_duration(source_video_path)
    offsets = _compute_offsets(duration, num_clips, clip_seconds)
    effective_clip_seconds = min(clip_seconds, duration)

    os.makedirs(output_dir, exist_ok=True)
    results = []
    for i, start in enumerate(offsets):
        end = min(start + effective_clip_seconds, duration)
        out_path = os.path.join(output_dir, f"clip_{i + 1}.mp4")

        # Re-encode rather than stream-copy (-c copy): a stream-copy cut
        # frequently lands on a non-keyframe and produces a frozen/black
        # first frame — these clips are short enough that the re-encode
        # cost is small, matching render_clip's own libx264/aac choice.
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-i", source_video_path,
            "-t", str(end - start),
            "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise ClipCutError(f"ffmpeg failed cutting clip {i + 1} (exit {result.returncode}): {result.stderr[-2000:]}")
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise ClipCutError(f"ffmpeg produced no output for clip {i + 1}")

        results.append({"path": out_path, "start": start, "end": end})

    return results
