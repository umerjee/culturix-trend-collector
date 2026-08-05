"""Tests for Phase 7 clip generation (app/routers/clips.py's orchestration).

This mocks each pipeline stage (script/TTS/image/transcription/render/
upload) rather than running the real Coqui TTS / faster-whisper / ffmpeg
pipeline end-to-end, matching this codebase's established test convention
(see tests/test_shopify_reels.py) of fast, network-free, mocked-provider
tests rather than slow live integration runs that need real model weights,
API keys, and an ffmpeg binary — that combination isn't something CI (or a
quick local run) should depend on. The individual service modules
(clip_script/clip_audio/clip_image/clip_transcribe/clip_render) are each
thin wrappers around a single external call, so unit-level mocking here
still exercises all the orchestration logic that's actually specific to
this feature: status transitions, DB persistence, upload paths, and
per-stage failure handling.
"""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.persona import Persona
from app.models.cluster import Cluster
from app.models.clip import Clip
from app.routers import clips as clips_router


@pytest.fixture
def clip_db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Persona.__table__, Cluster.__table__, Clip.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


@pytest.fixture
def persona(clip_db):
    session = clip_db()
    p = Persona(name="Quiet Luxury Devotee", description="Understated wealth aesthetic",
                motivations="status without logos", interests="minimalism, tailoring")
    session.add(p)
    session.commit()
    session.refresh(p)
    persona_id = p.id
    session.close()
    return persona_id


def _mock_pipeline_success(mocker, tmp_path, duration_seconds=32.5):
    mocker.patch("app.services.clip_script.generate_script", return_value="Hook line. " * 10)

    def _fake_voiceover(script_text, output_path):
        with open(output_path, "wb") as f:
            f.write(b"fake-wav-bytes")
        return output_path

    def _fake_image(source, output_path):
        with open(output_path, "wb") as f:
            f.write(b"fake-png-bytes")
        return output_path

    def _fake_render(image_path, audio_path, word_timestamps, output_path):
        with open(output_path, "wb") as f:
            f.write(b"fake-mp4-bytes")
        return {"video_path": output_path, "duration_seconds": duration_seconds}

    mocker.patch("app.services.clip_audio.generate_voiceover", side_effect=_fake_voiceover)
    mocker.patch("app.services.clip_image.get_or_generate_image", side_effect=_fake_image)
    mocker.patch(
        "app.services.clip_transcribe.transcribe_with_timestamps",
        return_value=[{"word": "hook", "start": 0.0, "end": 0.4}, {"word": "line", "start": 0.4, "end": 0.8}],
    )
    mocker.patch("app.services.clip_render.render_clip", side_effect=_fake_render)
    mocker.patch("app.media.storage.upload", return_value="https://supabase/fake-url")


class TestGenerateClip:
    def test_full_pipeline_marks_complete_and_persists_urls(self, clip_db, persona, mocker, tmp_path):
        _mock_pipeline_success(mocker, tmp_path)

        result = clips_router.generate_clip({"source_type": "persona", "source_id": persona})

        assert result["status"] == "complete"
        assert result["audio_path"] == "https://supabase/fake-url"
        assert result["image_path"] == "https://supabase/fake-url"
        assert result["video_path"] == "https://supabase/fake-url"
        assert result["duration_seconds"] == pytest.approx(32.5)
        assert result["script_text"]

        session = clip_db()
        row = session.query(Clip).first()
        assert row.status == "complete"
        session.close()

    def test_unknown_source_type_rejected(self, clip_db, persona):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            clips_router.generate_clip({"source_type": "trend", "source_id": persona})
        assert exc_info.value.status_code == 400

    def test_missing_persona_returns_404(self, clip_db):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            clips_router.generate_clip({"source_type": "persona", "source_id": 999999})
        assert exc_info.value.status_code == 404

    def test_tts_failure_marks_clip_failed_with_error(self, clip_db, persona, mocker):
        from fastapi import HTTPException
        from app.services.clip_audio import TTSGenerationError

        mocker.patch("app.services.clip_script.generate_script", return_value="A script.")
        mocker.patch("app.services.clip_audio.generate_voiceover",
                     side_effect=TTSGenerationError("model load failed"))

        with pytest.raises(HTTPException) as exc_info:
            clips_router.generate_clip({"source_type": "persona", "source_id": persona})

        assert exc_info.value.status_code == 500
        assert "model load failed" in exc_info.value.detail

        session = clip_db()
        row = session.query(Clip).first()
        assert row.status == "failed"
        assert "model load failed" in row.error_message
        # Script was generated and persisted even though a later stage failed.
        assert row.script_text == "A script."
        session.close()

    def test_render_failure_marks_clip_failed(self, clip_db, persona, mocker):
        from fastapi import HTTPException
        from app.services.clip_render import RenderError

        mocker.patch("app.services.clip_script.generate_script", return_value="A script.")
        mocker.patch("app.services.clip_audio.generate_voiceover",
                     side_effect=lambda text, path: open(path, "wb").write(b"x") or path)
        mocker.patch("app.services.clip_image.get_or_generate_image",
                     side_effect=lambda source, path: open(path, "wb").write(b"x") or path)
        mocker.patch("app.services.clip_transcribe.transcribe_with_timestamps", return_value=[])
        mocker.patch("app.services.clip_render.render_clip",
                     side_effect=RenderError("ffmpeg not found on PATH"))

        with pytest.raises(HTTPException) as exc_info:
            clips_router.generate_clip({"source_type": "persona", "source_id": persona})

        assert exc_info.value.status_code == 500
        session = clip_db()
        row = session.query(Clip).first()
        assert row.status == "failed"
        assert "ffmpeg" in row.error_message
        session.close()


class TestGetAndListClips:
    def test_get_clip_returns_serialized_row(self, clip_db, persona, mocker):
        _mock_pipeline_success(mocker, None)
        result = clips_router.generate_clip({"source_type": "persona", "source_id": persona})

        fetched = clips_router.get_clip(result["id"])
        assert fetched["id"] == result["id"]
        assert fetched["status"] == "complete"

    def test_list_clips_filters_by_status(self, clip_db, persona, mocker):
        _mock_pipeline_success(mocker, None)
        clips_router.generate_clip({"source_type": "persona", "source_id": persona})

        all_clips = clips_router.list_clips()
        assert len(all_clips) == 1

        failed_clips = clips_router.list_clips(status="failed")
        assert failed_clips == []

        complete_clips = clips_router.list_clips(status="complete")
        assert len(complete_clips) == 1
