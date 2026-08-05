"""Image generation for Phase 7 clips — reuses HybridImageProvider (Cloudflare
FLUX.1 schnell free tier -> Qwen paid fallback, see app/media/image_hybrid.py),
the same provider every other image asset in this app goes through, rather
than adding a second image stack.

Note: the original spec assumed a persona might already have an associated
"cartoon image" from an "Instagram pipeline" to reuse. No such field exists
on Persona in this codebase (checked app/models/persona.py) — there is no
Instagram-specific image pipeline here, so this always generates a fresh
image.
"""
import logging

from app.media.base import MediaResult
from app.models.persona import Persona

logger = logging.getLogger("culturix.services.clip_image")


class ImageGenerationError(Exception):
    pass


def _build_prompt(persona_or_cluster) -> str:
    if isinstance(persona_or_cluster, Persona):
        p = persona_or_cluster
        subject = f"{p.name}: {p.description}"
    else:
        c = persona_or_cluster
        subject = f"{c.theme}: {c.summary or ''}"

    return (
        f"Vertical 9:16 background image for a short-form social video about: {subject[:400]}. "
        f"Bold, high-contrast, editorial photography or illustration style, no embedded text, "
        f"clear visual focal point centered in the frame, clean space at top and bottom for "
        f"captions to be overlaid later."
    )


def get_or_generate_image(persona_or_cluster, output_path: str) -> str:
    from app.media.image_hybrid import HybridImageProvider

    prompt = _build_prompt(persona_or_cluster)
    try:
        result: MediaResult = HybridImageProvider().generate(prompt)
    except Exception as exc:
        raise ImageGenerationError(f"Image generation failed: {exc}") from exc

    if not result.asset_bytes:
        raise ImageGenerationError("Image generation produced no image data")

    with open(output_path, "wb") as f:
        f.write(result.asset_bytes)
    return output_path
