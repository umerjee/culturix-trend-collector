"""Tests for app/services/culturetoon_scene.py — independent per-scene
generation. Mirrors tests/test_culturetoon_video.py's shape/mocking
conventions exactly, scoped to a single shot instead of a whole script."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character_brand import CharacterBrand
from app.models.character import Character
from app.models.character_variant import CharacterVariant
from app.models.toon_episode import ToonEpisode
from app.models.toon_scene import ToonScene
from app.models.generation_usage import GenerationUsage
from app.services.culturetoon_scene import generate_scene_video


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        ToonEpisode.__table__, ToonScene.__table__, GenerationUsage.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


@pytest.fixture
def seeded(db):
    session = db()
    user_id = uuid.uuid4()
    brand = CharacterBrand(user_id=user_id, name="Test Brand")
    session.add(brand)
    session.commit()

    character = Character(brand_id=brand.id, name="Kumar")
    session.add(character)
    session.commit()

    variant = CharacterVariant(
        character_id=character.id, name="Kumar", image_url="https://img/kumar.png",
        kling_element_id="elem-1", kling_element_name="Kumar", element_status="ready",
    )
    session.add(variant)
    session.commit()

    episode = ToonEpisode(brand_id=brand.id, title="Swiss Recycling", status="draft")
    session.add(episode)
    session.commit()

    scene = ToonScene(
        episode_id=episode.id, brand_id=brand.id, scene_number=1,
        character_variant_ids=[str(variant.id)], action="Kumar arrives confused",
        dialogue="Why is there a bin for glass?", expression="Confused", duration_seconds=4,
    )
    session.add(scene)
    session.commit()

    ids = {
        "user_id": str(user_id), "brand_id": str(brand.id), "episode_id": str(episode.id),
        "scene_id": str(scene.id), "variant_id": str(variant.id),
    }
    session.close()
    return ids


def _mock_kling_success(mocker):
    mock_provider = mocker.patch("app.media.kling_omni.KlingOmniProvider")
    mock_provider.return_value.generate_omni_video.return_value = {
        "video_bytes": b"fake-mp4-bytes", "duration_seconds": 4.0, "task_id": "scene-task-1",
    }
    return mock_provider


class TestGenerateSceneVideoSuccess:
    def test_success_marks_ready_and_uploads(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/scene.mp4")

        generate_scene_video(seeded["user_id"], seeded["scene_id"])

        session = db()
        scene = session.query(ToonScene).filter_by(id=uuid.UUID(seeded["scene_id"])).first()
        assert scene.status == "ready"
        assert scene.video_url == "https://supabase/scene.mp4"
        assert scene.kling_task_id == "scene-task-1"
        assert scene.generation_error is None
        assert scene.generation_attempts == 1
        session.close()
        mock_upload.assert_called_once()

    def test_records_usage_with_episode_and_scene_id(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/scene.mp4")

        generate_scene_video(seeded["user_id"], seeded["scene_id"])

        session = db()
        rows = session.query(GenerationUsage).filter_by(scene_id=uuid.UUID(seeded["scene_id"])).all()
        assert len(rows) == 1
        assert rows[0].episode_id == uuid.UUID(seeded["episode_id"])
        assert rows[0].generation_type == "scene_video"
        session.close()

    def test_regeneration_archives_previous_video(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", side_effect=[
            "https://supabase/scene-v1.mp4", "https://supabase/scene-v2.mp4",
        ])

        generate_scene_video(seeded["user_id"], seeded["scene_id"])
        generate_scene_video(seeded["user_id"], seeded["scene_id"])

        session = db()
        scene = session.query(ToonScene).filter_by(id=uuid.UUID(seeded["scene_id"])).first()
        assert scene.video_url == "https://supabase/scene-v2.mp4"
        assert scene.previous_video_urls == ["https://supabase/scene-v1.mp4"]
        assert scene.generation_attempts == 2
        session.close()

    def test_builds_single_shot_prompt(self, db, seeded, mocker):
        mock_provider = _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/scene.mp4")

        generate_scene_video(seeded["user_id"], seeded["scene_id"])

        call = mock_provider.return_value.generate_omni_video.call_args
        contents, settings = call.args
        assert settings["multi_shot"] is False
        assert settings["duration"] == 4
        prompt_item = next(c for c in contents if c["type"] == "prompt")
        assert "@Kumar" in prompt_item["text"]
        assert "shot 1," in prompt_item["text"]
        assert prompt_item["text"].count("shot ") == 1  # exactly one shot, not a multi-shot script


class TestGenerateSceneVideoFailures:
    def test_no_cast_marks_failed(self, db, seeded, mocker):
        session = db()
        scene = session.query(ToonScene).filter_by(id=uuid.UUID(seeded["scene_id"])).first()
        scene.character_variant_ids = None
        session.commit()
        session.close()

        generate_scene_video(seeded["user_id"], seeded["scene_id"])

        session = db()
        scene = session.query(ToonScene).filter_by(id=uuid.UUID(seeded["scene_id"])).first()
        assert scene.status == "failed"
        assert "no cast" in scene.generation_error.lower()
        session.close()

    def test_unregistered_character_marks_failed(self, db, seeded, mocker):
        session = db()
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.element_status = "unregistered"
        session.commit()
        session.close()

        generate_scene_video(seeded["user_id"], seeded["scene_id"])

        session = db()
        scene = session.query(ToonScene).filter_by(id=uuid.UUID(seeded["scene_id"])).first()
        assert scene.status == "failed"
        assert "Kling element" in scene.generation_error
        session.close()

    def test_kling_error_marks_failed_and_still_counts_attempt(self, db, seeded, mocker):
        from app.media.kling_omni import KlingOmniError
        mock_provider = mocker.patch("app.media.kling_omni.KlingOmniProvider")
        mock_provider.return_value.generate_omni_video.side_effect = KlingOmniError("content risk control")

        generate_scene_video(seeded["user_id"], seeded["scene_id"])

        session = db()
        scene = session.query(ToonScene).filter_by(id=uuid.UUID(seeded["scene_id"])).first()
        assert scene.status == "failed"
        assert "content risk control" in scene.generation_error
        assert scene.generation_attempts == 1
        session.close()
