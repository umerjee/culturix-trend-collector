"""Tests for the episode-stitching background tasks
(app/services/culturetoon_episode.py) — mirrors tests/test_toon_publish.py's
structure (ToonPost's own background-task tests) for the same shape of
service: load row -> in-progress status -> do slow work -> write result
back -> catch-and-record-error -> finally: session.close()."""
import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

from app.db import Base
from app.models.toon_episode import ToonEpisode
from app.models.toon import Toon
from app.services.culturetoon_episode import stitch_episode, generate_episode_clips


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ToonEpisode.__table__, Toon.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_episode_with_parts(session, brand_id, part_video_urls):
    episode = ToonEpisode(brand_id=brand_id, title="Test Episode", status="stitching")
    session.add(episode)
    session.commit()
    for i, url in enumerate(part_video_urls):
        toon = Toon(
            brand_id=brand_id, character_variant_id=uuid.uuid4(), script_id=uuid.uuid4(),
            episode_id=episode.id, part_order=i, raw_video_url=url, status="ready",
        )
        session.add(toon)
    session.commit()
    return episode


class TestStitchEpisode:
    def test_success_concatenates_parts_and_uploads(self, mocker, db):
        session = db()
        brand_id = uuid.uuid4()
        episode = _make_episode_with_parts(session, brand_id, ["https://example.com/a.mp4", "https://example.com/b.mp4"])
        episode_id = str(episode.id)
        session.close()

        mocker.patch("app.services.culturetoon_episode.httpx.get", return_value=mocker.Mock(content=b"video-bytes", raise_for_status=lambda: None))
        mock_subprocess = mocker.patch("app.services.culturetoon_episode.subprocess.run", return_value=mocker.Mock(returncode=0, stderr=""))
        # ffmpeg's real output file won't exist under mocked subprocess.run, so
        # also patch builtins.open for the stitched-file read — simplest is to
        # patch storage.upload and let the earlier `open(stitched_path, "rb")`
        # fail... instead, patch subprocess.run's side effect to write the file.
        def _fake_run(cmd, **kwargs):
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"stitched-bytes")
            return mocker.Mock(returncode=0, stderr="")
        mock_subprocess.side_effect = _fake_run
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/episode-final.mp4")

        stitch_episode(str(uuid.uuid4()), episode_id)

        session = db()
        try:
            updated = session.query(ToonEpisode).filter_by(id=uuid.UUID(episode_id)).first()
            assert updated.status == "ready"
            assert updated.final_video_url == "https://supabase/episode-final.mp4"
            assert updated.generation_error is None
        finally:
            session.close()
        mock_upload.assert_called_once()

    def test_fewer_than_two_parts_marks_failed(self, mocker, db):
        session = db()
        brand_id = uuid.uuid4()
        episode = _make_episode_with_parts(session, brand_id, ["https://example.com/a.mp4"])
        episode_id = str(episode.id)
        session.close()

        stitch_episode(str(uuid.uuid4()), episode_id)

        session = db()
        try:
            updated = session.query(ToonEpisode).filter_by(id=uuid.UUID(episode_id)).first()
            assert updated.status == "failed"
            assert "at least 2 parts" in updated.generation_error
        finally:
            session.close()

    def test_part_missing_raw_video_marks_failed(self, mocker, db):
        session = db()
        brand_id = uuid.uuid4()
        episode = ToonEpisode(brand_id=brand_id, status="stitching")
        session.add(episode)
        session.commit()
        session.add(Toon(
            brand_id=brand_id, character_variant_id=uuid.uuid4(), script_id=uuid.uuid4(),
            episode_id=episode.id, part_order=0, raw_video_url="https://example.com/a.mp4", status="ready",
        ))
        session.add(Toon(
            brand_id=brand_id, character_variant_id=uuid.uuid4(), script_id=uuid.uuid4(),
            episode_id=episode.id, part_order=1, raw_video_url=None, status="animating",
        ))
        session.commit()
        episode_id = str(episode.id)
        session.close()

        stitch_episode(str(uuid.uuid4()), episode_id)

        session = db()
        try:
            updated = session.query(ToonEpisode).filter_by(id=uuid.UUID(episode_id)).first()
            assert updated.status == "failed"
            assert "1" in updated.generation_error
        finally:
            session.close()

    def test_ffmpeg_failure_marks_failed(self, mocker, db):
        session = db()
        brand_id = uuid.uuid4()
        episode = _make_episode_with_parts(session, brand_id, ["https://example.com/a.mp4", "https://example.com/b.mp4"])
        episode_id = str(episode.id)
        session.close()

        mocker.patch("app.services.culturetoon_episode.httpx.get", return_value=mocker.Mock(content=b"video-bytes", raise_for_status=lambda: None))
        mocker.patch("app.services.culturetoon_episode.subprocess.run", return_value=mocker.Mock(returncode=1, stderr="ffmpeg exploded"))

        stitch_episode(str(uuid.uuid4()), episode_id)

        session = db()
        try:
            updated = session.query(ToonEpisode).filter_by(id=uuid.UUID(episode_id)).first()
            assert updated.status == "failed"
            assert "ffmpeg" in updated.generation_error.lower()
        finally:
            session.close()


class TestGenerateEpisodeClips:
    def test_requires_final_video_url(self, mocker, db):
        session = db()
        episode = ToonEpisode(brand_id=uuid.uuid4(), status="ready")
        session.add(episode)
        session.commit()
        episode_id = str(episode.id)
        session.close()

        generate_episode_clips(str(uuid.uuid4()), episode_id)

        session = db()
        try:
            updated = session.query(ToonEpisode).filter_by(id=uuid.UUID(episode_id)).first()
            assert "stitch it first" in updated.generation_error.lower()
        finally:
            session.close()

    def test_success_writes_clip_urls(self, mocker, db):
        session = db()
        episode = ToonEpisode(brand_id=uuid.uuid4(), status="ready", final_video_url="https://example.com/final.mp4")
        session.add(episode)
        session.commit()
        episode_id = str(episode.id)
        session.close()

        mocker.patch("app.services.culturetoon_episode.httpx.get", return_value=mocker.Mock(content=b"video-bytes", raise_for_status=lambda: None))
        mocker.patch(
            "app.services.culturetoon_clip_cutter.cut_clips",
            return_value=[{"path": "/tmp/clip_1.mp4", "start": 0, "end": 8}, {"path": "/tmp/clip_2.mp4", "start": 8, "end": 16}],
        )
        mocker.patch("builtins.open", mocker.mock_open(read_data=b"clip-bytes"))
        mock_upload = mocker.patch("app.media.storage.upload", side_effect=["https://supabase/clip1.mp4", "https://supabase/clip2.mp4"])

        generate_episode_clips(str(uuid.uuid4()), episode_id)

        session = db()
        try:
            updated = session.query(ToonEpisode).filter_by(id=uuid.UUID(episode_id)).first()
            assert updated.clip_video_urls == ["https://supabase/clip1.mp4", "https://supabase/clip2.mp4"]
        finally:
            session.close()
        assert mock_upload.call_count == 2
