"""Tests for app/services/culturetoon_shot.py — independent per-shot
generation, the fine-grained production unit beneath ToonScene. Mirrors
tests/test_culturetoon_scene.py's shape/mocking conventions."""
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
from app.models.toon_shot import ToonShot
from app.models.toon_background import ToonBackground
from app.models.generation_usage import GenerationUsage
from app.services.culturetoon_shot import generate_shot_video, build_shot_prompt


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        ToonEpisode.__table__, ToonScene.__table__, ToonShot.__table__,
        ToonBackground.__table__, GenerationUsage.__table__,
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

    background = ToonBackground(brand_id=brand.id, name="Recycling Station", image_url="https://img/bg.png", description="A Swiss recycling station")
    session.add(background)
    session.commit()

    episode = ToonEpisode(brand_id=brand.id, title="Kumar's Recycling Adventure", status="draft")
    session.add(episode)
    session.commit()

    scene = ToonScene(episode_id=episode.id, brand_id=brand.id, scene_number=1, background_id=background.id)
    session.add(scene)
    session.commit()

    shot = ToonShot(
        scene_id=scene.id, brand_id=brand.id, shot_number=1, shot_type="medium",
        duration_seconds=3, character_variant_ids=[str(variant.id)],
        action="Kumar looks confused", emotion="Confused", dialogue="What is this bin for?",
        comedic_beat="setup", camera_angle="eye level", camera_movement="static",
    )
    session.add(shot)
    session.commit()

    ids = {
        "user_id": str(user_id), "brand_id": str(brand.id), "episode_id": str(episode.id),
        "scene_id": str(scene.id), "shot_id": str(shot.id), "variant_id": str(variant.id),
        "background_id": str(background.id),
    }
    session.close()
    return ids


def _mock_kling_success(mocker):
    mock_provider = mocker.patch("app.media.kling_omni.KlingOmniProvider")
    mock_provider.return_value.generate_omni_video.return_value = {
        "video_bytes": b"fake-mp4-bytes", "duration_seconds": 3.0, "task_id": "shot-task-1",
    }
    return mock_provider


class TestBuildShotPrompt:
    def test_includes_shot_type_camera_and_dialogue(self, mocker):
        shot = mocker.Mock(
            character_variant_ids=["v1"], shot_type="closeup", camera_angle="low angle",
            camera_movement="push_in", lens="85mm", composition="rule of thirds", lighting="warm",
            action="reacts in shock", emotion="Shocked", dialogue="No way!",
        )
        text = build_shot_prompt(shot, "Kumar", location_description="a kitchen")
        assert "@Kumar" in text
        assert "closeup shot" in text
        assert "low angle" in text
        assert "push in camera movement" in text
        assert "reacts in shock" in text
        assert "shocked expression" in text
        assert 'saying "No way!"' in text
        assert "Setting: a kitchen." in text

    def test_static_movement_omitted(self, mocker):
        shot = mocker.Mock(
            character_variant_ids=[], shot_type="wide", camera_angle=None, camera_movement="static",
            lens=None, composition=None, lighting=None, action=None, emotion=None, dialogue=None,
        )
        text = build_shot_prompt(shot, {})
        assert "camera movement" not in text

    def test_no_cast_no_element_reference(self, mocker):
        shot = mocker.Mock(
            character_variant_ids=[], shot_type="establishing", camera_angle=None, camera_movement=None,
            lens=None, composition=None, lighting=None, action="empty street", emotion=None, dialogue=None,
        )
        text = build_shot_prompt(shot, {})
        assert "@" not in text

    def test_truncates_to_max_length(self, mocker):
        shot = mocker.Mock(
            character_variant_ids=["v1"], shot_type="medium", camera_angle=None, camera_movement=None,
            lens=None, composition=None, lighting=None, action="x" * 1000, emotion=None, dialogue=None,
        )
        text = build_shot_prompt(shot, "Kumar")
        assert len(text) <= 512


class TestGenerateShotVideoSuccess:
    def test_success_marks_ready_and_uploads(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/shot.mp4")

        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        assert shot.generation_status == "ready"
        assert shot.generated_asset_id == "https://supabase/shot.mp4"
        assert shot.kling_task_id == "shot-task-1"
        assert shot.generation_error is None
        assert shot.generation_attempts == 1
        assert shot.visual_prompt is not None
        assert "Setting: A Swiss recycling station" in shot.visual_prompt
        session.close()
        mock_upload.assert_called_once()

    def test_resolves_location_from_scene_when_shot_has_none(self, db, seeded, mocker):
        # shot.background_id is unset — must inherit the parent scene's.
        _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/shot.mp4")

        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        assert "recycling station" in shot.visual_prompt.lower()
        session.close()

    def test_records_usage_with_episode_scene_and_shot_id(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/shot.mp4")

        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        rows = session.query(GenerationUsage).filter_by(shot_id=uuid.UUID(seeded["shot_id"])).all()
        assert len(rows) == 1
        assert rows[0].scene_id == uuid.UUID(seeded["scene_id"])
        assert rows[0].episode_id == uuid.UUID(seeded["episode_id"])
        assert rows[0].generation_type == "shot_video"
        session.close()

    def test_regeneration_archives_previous_asset(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", side_effect=[
            "https://supabase/shot-v1.mp4", "https://supabase/shot-v2.mp4",
        ])

        generate_shot_video(seeded["user_id"], seeded["shot_id"])
        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        assert shot.generated_asset_id == "https://supabase/shot-v2.mp4"
        assert shot.previous_asset_ids == ["https://supabase/shot-v1.mp4"]
        assert shot.generation_attempts == 2
        session.close()

    def test_reference_assets_recorded(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/shot.mp4")

        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        assert "https://img/kumar.png" in shot.reference_assets
        assert "https://img/bg.png" in shot.reference_assets
        session.close()

    def test_environmental_shot_with_no_cast_still_generates(self, db, seeded, mocker):
        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        shot.character_variant_ids = None
        shot.shot_type = "establishing"
        session.commit()
        session.close()

        _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/shot.mp4")

        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        assert shot.generation_status == "ready"
        session.close()


class TestGenerateShotVideoFailures:
    def test_unregistered_character_marks_failed(self, db, seeded, mocker):
        session = db()
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.element_status = "unregistered"
        session.commit()
        session.close()

        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        assert shot.generation_status == "failed"
        assert "Kling element" in shot.generation_error
        session.close()

    def test_kling_error_marks_failed_and_still_counts_attempt(self, db, seeded, mocker):
        from app.media.kling_omni import KlingOmniError
        mock_provider = mocker.patch("app.media.kling_omni.KlingOmniProvider")
        mock_provider.return_value.generate_omni_video.side_effect = KlingOmniError("content risk control")

        generate_shot_video(seeded["user_id"], seeded["shot_id"])

        session = db()
        shot = session.query(ToonShot).filter_by(id=uuid.UUID(seeded["shot_id"])).first()
        assert shot.generation_status == "failed"
        assert "content risk control" in shot.generation_error
        assert shot.generation_attempts == 1
        session.close()
