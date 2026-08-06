"""Image generation for faceless-reel media generation — reuses
HybridImageProvider (Cloudflare FLUX.1 schnell free tier -> Qwen paid
fallback, see app/media/image_hybrid.py), the same provider every other
image asset in this app goes through, rather than adding a second image
stack.

Generates one image per script segment (see app/services/reel_pipeline.py's
word-timestamp-driven segmentation) instead of one static image for the
whole clip — real faceless reels cut between visuals rather than holding
one still frame for 30-45s; a single unchanging image was the piece that
made the original Phase 7 pipeline read as far more static than the format
actually calls for. Segment TEXT is passed in already split by the caller
(not re-split here from scratch) so the images line up with exactly the
same word groupings driving caption timing — splitting independently in
two places risked a visual changing at a different moment than what's
actually being said.
"""
import logging
import os

from app.media.base import MediaResult

logger = logging.getLogger("culturix.services.clip_image")


class ImageGenerationError(Exception):
    pass


def _build_prompt(segment_text: str) -> str:
    return (
        f"Vertical 9:16 background image for a short-form social video, illustrating this moment: "
        f"{segment_text.strip()[:400]}. "
        f"Bold, high-contrast, editorial photography or illustration style, no embedded text, "
        f"clear visual focal point centered in the frame, clean space at top and bottom for "
        f"captions to be overlaid later."
    )


def generate_segment_images(segments: list, output_dir: str) -> list:
    """segments: list of segment text strings, in order. Returns
    [image_path, ...] in the same order, one PNG per segment."""
    from app.media.image_hybrid import HybridImageProvider

    if not segments:
        raise ImageGenerationError("Cannot generate images from an empty segment list")

    provider = HybridImageProvider()
    paths = []
    for i, segment_text in enumerate(segments):
        prompt = _build_prompt(segment_text)
        try:
            result: MediaResult = provider.generate(prompt)
        except Exception as exc:
            raise ImageGenerationError(f"Image generation failed for segment {i + 1}: {exc}") from exc
        if not result.asset_bytes:
            raise ImageGenerationError(f"Image generation produced no image data for segment {i + 1}")
        path = os.path.join(output_dir, f"image_{i}.png")
        with open(path, "wb") as f:
            f.write(result.asset_bytes)
        paths.append(path)
    return paths
