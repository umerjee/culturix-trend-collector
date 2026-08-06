"""Orchestrates faceless-reel generation end to end: script -> voiceover
(+ real per-word timestamps) -> N segment images -> ffmpeg render with
burned-in captions. Registered as the "reel" media_type in
app/media/service.py's run_generation dispatch — unlike every other media
type there, this composes several steps internally rather than calling one
provider's .generate(), but still returns the same shared MediaResult
(app/media/base.py) so it flows through run_generation's existing
upload/DB-update tail unmodified.
"""
import logging
import os
import tempfile

from app.media.base import MediaResult

logger = logging.getLogger("culturix.services.reel_pipeline")

# Fixed, not derived from script length — bounds cost/time per reel. Real
# faceless reels cut more often (every 2-4s) but that's materially more
# image-generation cost for a bootstrapped product; easy to raise later once
# real usage data exists. Mirrors the same bounded-constant precedent as
# CultureToons' MAX_CHARACTERS_PER_VIDEO.
NUM_IMAGE_SEGMENTS = 3


class ReelGenerationError(Exception):
    pass


def _split_words_into_segments(words: list, num_segments: int) -> list:
    """words: [{"word","start","end"}, ...] in order, from the real TTS
    word timestamps (not an estimated speaking rate). Returns
    [(segment_text, start), ...] — each segment's real measured start time,
    so its image's on-screen duration (computed by the caller from
    consecutive segments' start times) matches what's actually being said
    while it's showing."""
    if not words:
        return []
    chunk_size = max(1, -(-len(words) // num_segments))  # ceil division
    segments = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        text = " ".join(w["word"] for w in chunk)
        segments.append((text, chunk[0]["start"]))
    return segments


def run_reel_pipeline(idea_text: str) -> MediaResult:
    """idea_text: the idea's hook/caption/cta, composed by the caller (see
    DigestCard.tsx's prompts.reel) — same input every other media type's
    prompt already is, a plain string."""
    from app.services.clip_script import generate_script, ScriptGenerationError
    from app.services.clip_audio import generate_voiceover_with_timestamps, TTSGenerationError
    from app.services.clip_image import generate_segment_images, ImageGenerationError
    from app.services.clip_render import render_clip, RenderError

    try:
        script_text = generate_script(idea_text)
    except ScriptGenerationError as exc:
        raise ReelGenerationError(f"Script generation failed: {exc}") from exc

    with tempfile.TemporaryDirectory(prefix="reel-") as tmp_dir:
        audio_path = os.path.join(tmp_dir, "voice.mp3")
        try:
            words = generate_voiceover_with_timestamps(script_text, audio_path)
        except TTSGenerationError as exc:
            raise ReelGenerationError(f"Voiceover generation failed: {exc}") from exc

        segments = _split_words_into_segments(words, NUM_IMAGE_SEGMENTS)
        if not segments:
            raise ReelGenerationError("No word timestamps to build video segments from")

        try:
            image_paths = generate_segment_images([text for text, _ in segments], tmp_dir)
        except ImageGenerationError as exc:
            raise ReelGenerationError(f"Image generation failed: {exc}") from exc

        # Segment i's duration runs from its own start to the NEXT segment's
        # start (not its own last word's end) so there's no silent/frozen
        # gap between images. The first segment starts at 0 (covers any
        # leading silence before the first word). The last segment gets a
        # 1s safety buffer past the last word's end — render_clip's final
        # mux uses -shortest, which safely trims any excess but can't
        # recover audio if a segment under-shoots and cuts it off early.
        render_segments = []
        for i, (_text, start) in enumerate(segments):
            seg_start = 0.0 if i == 0 else start
            if i + 1 < len(segments):
                next_start = segments[i + 1][1]
            else:
                next_start = words[-1]["end"] + 1.0
            duration = max(0.5, next_start - seg_start)
            render_segments.append((image_paths[i], duration))

        video_path = os.path.join(tmp_dir, "reel.mp4")
        try:
            render_result = render_clip(render_segments, audio_path, words, video_path)
        except RenderError as exc:
            raise ReelGenerationError(f"Video render failed: {exc}") from exc

        with open(video_path, "rb") as f:
            video_bytes = f.read()

    return MediaResult(
        asset_bytes=video_bytes,
        content_type="video/mp4",
        duration_seconds=render_result["duration_seconds"],
        cost_usd=None,
    )
