"""Shared image-upload helper for CultureToons — characters, variants,
expressions, and backgrounds all upload a reference PNG/WebP/JPEG through
this one path rather than each hand-rolling validation. Reuses
app/media/storage.py's existing Supabase Storage upload() unchanged (it
already handles the 409-conflict upsert-via-PUT case, so re-uploading to
replace an image just works).
"""
_ALLOWED_CONTENT_TYPES = {"image/png", "image/webp", "image/jpeg"}
_MAX_BYTES = 10 * 1024 * 1024


class ImageUploadError(Exception):
    pass


def save_image(data: bytes, content_type: str, path: str) -> str:
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise ImageUploadError(f"Unsupported content type: {content_type} (expected PNG or WebP)")
    if not data:
        raise ImageUploadError("No image data received")
    if len(data) > _MAX_BYTES:
        raise ImageUploadError("Image exceeds 10MB limit")

    from app.media import storage
    return storage.upload(data, path, content_type)
