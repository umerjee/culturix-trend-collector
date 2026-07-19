"""Media generation service — orchestrates provider + storage + DB update."""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("culturix.media")

_PROVIDERS = {
    "voiceover": ("edge-tts",   "app.media.voice", "EdgeTTSProvider"),
    "music":     ("minimax",    "app.media.music", "MiniMaxMusicProvider"),
    "video":     ("kling",      "app.media.video",  "KlingProvider"),
}

_EXT = {
    "audio/mpeg": "mp3",
    "video/mp4":  "mp4",
}


def _get_provider(media_type: str):
    _, module_path, class_name = _PROVIDERS[media_type]
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


def _update_row(row_id: str, **kwargs):
    from app.db import SessionLocal
    from app.models.generated_media import GeneratedMedia
    import uuid as _uuid
    session = SessionLocal()
    try:
        row = session.query(GeneratedMedia).filter_by(id=_uuid.UUID(row_id)).first()
        if row:
            for k, v in kwargs.items():
                setattr(row, k, v)
            session.commit()
    finally:
        session.close()


def run_generation(
    row_id: str,
    media_type: str,
    prompt: str,
    user_id: str,
    content_id: str,
    idea_index: int,
) -> None:
    """Called as a background task. Updates the DB row when done or failed."""
    _update_row(row_id, status="processing")
    try:
        provider = _get_provider(media_type)

        if media_type == "voiceover":
            result = provider.synthesize(prompt)
        elif media_type == "music":
            result = provider.generate(prompt)
        elif media_type == "video":
            result = provider.generate(prompt)
        else:
            raise ValueError(f"Unknown media_type: {media_type}")

        ext = _EXT.get(result.content_type, "bin")
        storage_path = f"{user_id}/{content_id}/{idea_index}-{media_type}.{ext}"

        from app.media import storage
        public_url = storage.upload(result.asset_bytes, storage_path, result.content_type)

        _update_row(
            row_id,
            status="done",
            asset_url=public_url,
            duration_seconds=result.duration_seconds,
            cost_usd=result.cost_usd,
            completed_at=datetime.utcnow(),
        )
        logger.info("Media done: %s %s → %s", media_type, row_id, public_url)

    except Exception as exc:
        logger.error("Media generation failed (%s %s): %s", media_type, row_id, exc)
        _update_row(row_id, status="failed", error=str(exc), completed_at=datetime.utcnow())
