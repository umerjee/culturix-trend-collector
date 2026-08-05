"""Phase 7 — clip generation orchestration endpoint. Turns a persona or
cluster into a short-form vertical video (script -> voiceover -> image ->
word-timestamp transcription -> ffmpeg render), synchronously within the
request per the v1 spec (no background job queue yet).

NOTE: running this synchronously is a known risk, not an oversight. Coqui
TTS on CPU alone can take 20-60s, plus faster-whisper transcription and an
ffmpeg render on top of that. This app already has a precedent for exactly
this situation — app/shopify/reels.py's Kling reel generation (up to ~6
minutes) runs as a BackgroundTasks job with the row polled for status
instead of blocking the request. Worth revisiting before this goes beyond
manual/local use, since a request handler this slow risks tripping any HTTP
gateway timeout sitting in front of it.
"""
import logging
import os
import tempfile
import uuid as _uuid

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("culturix.routers.clips")
router = APIRouter()

_VALID_SOURCE_TYPES = {"persona", "cluster"}


def _fetch_source(session, source_type: str, source_id: int):
    if source_type == "persona":
        from app.models.persona import Persona
        return session.query(Persona).filter_by(id=source_id).first()
    from app.models.cluster import Cluster
    return session.query(Cluster).filter_by(id=source_id).first()


def _serialize(clip) -> dict:
    return {
        "id": str(clip.id),
        "source_type": clip.source_type,
        "source_id": clip.source_id,
        "script_text": clip.script_text,
        "audio_path": clip.audio_path,
        "image_path": clip.image_path,
        "video_path": clip.video_path,
        "duration_seconds": float(clip.duration_seconds) if clip.duration_seconds is not None else None,
        "status": clip.status,
        "error_message": clip.error_message,
        "created_at": clip.created_at.isoformat() if clip.created_at else None,
    }


def _run_pipeline(clip_id: str, source_type: str, source_id: int) -> None:
    from app.db import SessionLocal
    from app.models.clip import Clip
    from app.services.clip_script import generate_script, ScriptGenerationError
    from app.services.clip_audio import generate_voiceover, TTSGenerationError
    from app.services.clip_image import get_or_generate_image, ImageGenerationError
    from app.services.clip_transcribe import transcribe_with_timestamps, TranscriptionError
    from app.services.clip_render import render_clip, RenderError
    from app.media import storage

    session = SessionLocal()
    try:
        clip = session.query(Clip).filter_by(id=_uuid.UUID(clip_id)).first()
        if not clip:
            return

        clip.status = "processing"
        session.commit()

        source = _fetch_source(session, source_type, source_id)
        if not source:
            raise ValueError(f"{source_type} {source_id} not found")

        with tempfile.TemporaryDirectory(prefix=f"clip-{clip_id}-") as tmp_dir:
            audio_path = os.path.join(tmp_dir, "voice.wav")
            image_path = os.path.join(tmp_dir, "image.png")
            video_path = os.path.join(tmp_dir, "video.mp4")

            script_text = generate_script(source)
            clip.script_text = script_text
            session.commit()

            generate_voiceover(script_text, audio_path)
            get_or_generate_image(source, image_path)
            word_timestamps = transcribe_with_timestamps(audio_path)
            render_result = render_clip(image_path, audio_path, word_timestamps, video_path)

            base_path = f"clips/{clip_id}"
            with open(audio_path, "rb") as f:
                audio_url = storage.upload(f.read(), f"{base_path}/voice.wav", "audio/wav")
            with open(image_path, "rb") as f:
                image_url = storage.upload(f.read(), f"{base_path}/image.png", "image/png")
            with open(video_path, "rb") as f:
                video_url = storage.upload(f.read(), f"{base_path}/video.mp4", "video/mp4")

        clip.audio_path = audio_url
        clip.image_path = image_url
        clip.video_path = video_url
        clip.duration_seconds = render_result["duration_seconds"]
        clip.status = "complete"
        session.commit()
        logger.info("Clip %s complete (%s %s)", clip_id, source_type, source_id)

    except (ScriptGenerationError, TTSGenerationError, ImageGenerationError,
            TranscriptionError, RenderError, ValueError) as exc:
        session.rollback()
        clip = session.query(Clip).filter_by(id=_uuid.UUID(clip_id)).first()
        if clip:
            clip.status = "failed"
            clip.error_message = str(exc)
            session.commit()
        logger.error("Clip %s failed: %s", clip_id, exc)
    except Exception as exc:
        session.rollback()
        clip = session.query(Clip).filter_by(id=_uuid.UUID(clip_id)).first()
        if clip:
            clip.status = "failed"
            clip.error_message = f"Unexpected error: {exc}"
            session.commit()
        logger.exception("Clip %s failed unexpectedly", clip_id)
    finally:
        session.close()


@router.post("/generate/clip")
def generate_clip(body: dict):
    """Body: { "source_type": "persona" | "cluster", "source_id": int }
    Runs synchronously (v1 — no background job queue yet) and returns the
    completed Clip row, or a 500 with error_message if generation failed."""
    from app.db import SessionLocal
    from app.models.clip import Clip

    source_type = body.get("source_type")
    source_id = body.get("source_id")
    if source_type not in _VALID_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="source_type must be 'persona' or 'cluster'")
    if source_id is None:
        raise HTTPException(status_code=400, detail="source_id is required")
    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="source_id must be an integer")

    session = SessionLocal()
    try:
        source = _fetch_source(session, source_type, source_id)
        if not source:
            raise HTTPException(status_code=404, detail=f"{source_type} {source_id} not found")

        clip = Clip(source_type=source_type, source_id=source_id, status="pending")
        session.add(clip)
        session.commit()
        session.refresh(clip)
        clip_id = str(clip.id)
    finally:
        session.close()

    _run_pipeline(clip_id, source_type, source_id)

    session2 = SessionLocal()
    try:
        clip = session2.query(Clip).filter_by(id=_uuid.UUID(clip_id)).first()
        if not clip:
            raise HTTPException(status_code=500, detail="Clip row disappeared during generation")
        if clip.status == "failed":
            raise HTTPException(status_code=500, detail=clip.error_message or "Clip generation failed")
        return _serialize(clip)
    finally:
        session2.close()


@router.get("/clips/{clip_id}")
def get_clip(clip_id: str):
    from app.db import SessionLocal
    from app.models.clip import Clip

    try:
        clip_uuid = _uuid.UUID(clip_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid clip id")

    session = SessionLocal()
    try:
        clip = session.query(Clip).filter_by(id=clip_uuid).first()
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        return _serialize(clip)
    finally:
        session.close()


@router.get("/clips")
def list_clips(source_type: str = None, status: str = None, limit: int = 50):
    from app.db import SessionLocal
    from app.models.clip import Clip

    session = SessionLocal()
    try:
        query = session.query(Clip)
        if source_type:
            query = query.filter(Clip.source_type == source_type)
        if status:
            query = query.filter(Clip.status == status)
        clips = query.order_by(Clip.created_at.desc()).limit(min(limit, 200)).all()
        return [_serialize(c) for c in clips]
    finally:
        session.close()
