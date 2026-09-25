"""Dedicated, purpose-built thumbnails for World Features — one fixed, branded visual style
shared by the whole catalog, so every card in the /world grid looks like part of one system
regardless of what a subject's real Wikipedia lead image looks like (a 19th-century map next
to a macro photo next to a scientific ribbon diagram next to a coat of arms — each accurate,
none consistent with the others, confirmed live).

Deliberately NOT tied to a video's own visual_style (illustrated_history/graphic_novel/
photorealistic default): most Features render photorealistic, so keying the thumbnail to
that would still leave a mostly-inconsistent grid. One style, always, is what actually
solves "consistent during all production."

Uses the same image-generation path CultureToons already relies on
(app/media/image_hybrid.py's HybridImageProvider — Cloudflare Workers AI's free tier first,
Qwen-Image only on failure) rather than a new provider, and the same storage.upload() every
other generated asset in this app goes through.
"""
import logging

logger = logging.getLogger("culturix.services.world_thumbnail")

# Positive description only — telling the model what NOT to draw measured worst on a real
# comparison for this exact video pipeline (see WORLD_VISUAL_STYLES's own comment in
# world_production.py); same lesson applied here. Portrait orientation matches the 9:16
# card aspect ratio every thumbnail renders into.
WORLD_THUMBNAIL_STYLE = (
    "Minimalist editorial illustration, flat design, bold simple geometric shapes, muted "
    "purple and warm cream color palette, clean uncluttered composition, subtle paper grain "
    "texture, portrait orientation, no text, no logos, no watermark."
)


def build_world_thumbnail_prompt(subject_text: str) -> str:
    return f"{subject_text.strip()}. {WORLD_THUMBNAIL_STYLE}"


def generate_world_thumbnail(toon_id: str, subject_text: str) -> str | None:
    """Generates and uploads one thumbnail, returns its public URL, or None on any failure
    (fails open — a thumbnail is a nice-to-have, never worth blocking script/video
    generation over). Does not write to the database itself; the caller decides when to
    persist the URL, matching every other media-generation call site's own separation of
    "produce the asset" from "record it," so a caller mid-transaction isn't forced to
    commit here."""
    try:
        from app.media.image_hybrid import HybridImageProvider
        from app.media import storage

        prompt = build_world_thumbnail_prompt(subject_text)
        result = HybridImageProvider().generate(prompt)
        ext = "png" if result.content_type == "image/png" else "jpg"
        url = storage.upload(result.asset_bytes, f"world-thumbnails/{toon_id}.{ext}", result.content_type)
        logger.info("Generated World thumbnail for %s (cost=%s)", toon_id, result.cost_usd)
        return url
    except Exception:
        logger.warning("World thumbnail generation failed for %s", toon_id, exc_info=True)
        return None
