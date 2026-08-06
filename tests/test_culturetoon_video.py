"""Tests for app/services/culturetoon_video.py — the Kling Omni generation
orchestration. Mirrors tests/test_shopify_reels.py's
TestGenerateReelForProduct shape: in-memory SQLite, every external call
(Kling, storage) mocked, no real network/ffmpeg needed.
"""
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
from app.models.toon_background import ToonBackground
from app.models.toon_script import ToonScript
from app.models.toon import Toon
from app.models.generation_usage import GenerationUsage
from app.services.culturetoon_video import generate_video_for_toon

_SHOTS = [
    {"shot_number": 1, "duration_seconds": 4, "action": "storms in", "expression": "Annoyed", "dialogue": "You didn't eat?!"},
    {"shot_number": 2, "duration_seconds": 4, "action": "softens", "expression": "Smiling", "dialogue": None},
]


@pytest.fixture(autouse=True)
def _no_real_ai_judge_call(mocker):
    # run_ai_judge_qa makes a real Qwen/Claude call when QWEN_API_KEY/
    # ANTHROPIC_API_KEY are set in the environment (they are, via .env) —
    # every successful-generation test would otherwise make a real, billed
    # LLM call on every test run. Autouse so it's opt-out, not opt-in.
    # run_technical_qa is left real — ffmpeg.probe() on the fake video
    # bytes these tests upload just fails harmlessly (no network, no cost),
    # which is itself useful coverage of the QA wiring's failure path.
    return mocker.patch(
        "app.services.culturetoon_qa.run_ai_judge_qa",
        return_value={"comedy_score": 80, "cultural_score": 90, "cultural_concerns": [], "reasoning": "mocked", "judge_failed": False},
    )


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        ToonBackground.__table__, ToonScript.__table__, Toon.__table__,
        GenerationUsage.__table__,
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

    character = Character(brand_id=brand.id, name="Base")
    session.add(character)
    session.commit()

    variant = CharacterVariant(
        character_id=character.id, name="Mom", image_url="https://img/mom.png",
        kling_element_id="elem-1", kling_element_name="Mom", element_status="ready",
    )
    session.add(variant)
    session.commit()

    script = ToonScript(brand_id=brand.id, character_variant_id=variant.id, shots=_SHOTS, total_duration_seconds=8)
    session.add(script)
    session.commit()

    toon = Toon(brand_id=brand.id, character_variant_id=variant.id, script_id=script.id, status="animating")
    session.add(toon)
    session.commit()

    ids = {"user_id": str(user_id), "brand_id": str(brand.id), "toon_id": str(toon.id), "variant_id": str(variant.id)}
    session.close()
    return ids


@pytest.fixture
def seeded_two_variants(db):
    session = db()
    user_id = uuid.uuid4()
    brand = CharacterBrand(user_id=user_id, name="Test Brand")
    session.add(brand)
    session.commit()

    character = Character(brand_id=brand.id, name="Base")
    session.add(character)
    session.commit()

    kumar = CharacterVariant(
        character_id=character.id, name="Kumar", image_url="https://img/kumar.png",
        kling_element_id="elem-kumar", kling_element_name="Kumar", element_status="ready",
    )
    wife = CharacterVariant(
        character_id=character.id, name="Wife", image_url="https://img/wife.png",
        kling_element_id="elem-wife", kling_element_name="Wife", element_status="ready",
    )
    session.add_all([kumar, wife])
    session.commit()

    multi_shots = [
        {"shot_number": 1, "duration_seconds": 4, "action": "storms in", "expression": "Annoyed",
         "dialogue": "Where were you?!", "speaker_variant_id": str(wife.id)},
        {"shot_number": 2, "duration_seconds": 4, "action": "shrugs", "expression": "Deadpan",
         "dialogue": "Traffic.", "speaker_variant_id": str(kumar.id)},
    ]
    script = ToonScript(
        brand_id=brand.id, character_variant_id=kumar.id, character_variant_ids=[str(kumar.id), str(wife.id)],
        shots=multi_shots, total_duration_seconds=8,
    )
    session.add(script)
    session.commit()

    toon = Toon(brand_id=brand.id, character_variant_id=kumar.id, script_id=script.id, status="animating")
    session.add(toon)
    session.commit()

    ids = {
        "user_id": str(user_id), "brand_id": str(brand.id), "toon_id": str(toon.id),
        "kumar_id": str(kumar.id), "wife_id": str(wife.id),
    }
    session.close()
    return ids


def _mock_kling_success(mocker):
    mock_provider = mocker.patch("app.media.kling_omni.KlingOmniProvider")
    mock_provider.return_value.generate_omni_video.return_value = {
        "video_bytes": b"fake-mp4-bytes", "duration_seconds": 8.0, "task_id": "task-123",
    }
    return mock_provider


class TestGenerateVideoForToonSuccess:
    def test_native_kling_audio_path(self, db, seeded, mocker):
        _mock_kling_success(mocker)
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "ready"
        assert toon.raw_video_url == "https://supabase/video.mp4"
        assert toon.final_video_url == "https://supabase/video.mp4"
        assert toon.kling_task_id == "task-123"
        assert toon.generation_error is None
        # QA (Phase 7a+7b) runs automatically — technical checks fail on
        # the fake (non-mp4) video bytes these tests upload, so
        # publish_recommended is correctly False here; this is exercising
        # the real run_technical_qa path, only the LLM half is mocked (see
        # the _no_real_ai_judge_call autouse fixture).
        assert toon.qa_results is not None
        assert toon.publish_recommended is False
        session.close()

        mock_upload.assert_called()

    def test_records_generation_usage_for_video(self, db, seeded, mocker):
        from decimal import Decimal
        _mock_kling_success(mocker)  # duration_seconds=8.0
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        session = db()
        rows = session.query(GenerationUsage).filter_by(toon_id=uuid.UUID(seeded["toon_id"])).all()
        assert len(rows) == 1
        assert rows[0].provider == "kling_omni"
        assert rows[0].generation_type == "video"
        assert rows[0].cost_usd == Decimal("0.6720")
        session.close()

    def test_regeneration_archives_previous_video_instead_of_discarding_it(self, db, seeded, mocker):
        # Confirmed live: regenerating used to silently overwrite
        # raw_video_url/final_video_url with no way back to a previous,
        # otherwise-good take. Also locks in that each generation gets its
        # own unique storage path — storage.upload upserts on conflict, so
        # a fixed path would let the second generation overwrite the first
        # take's own file underneath the URL now sitting in history.
        _mock_kling_success(mocker)
        mock_upload = mocker.patch("app.media.storage.upload", side_effect=[
            "https://supabase/video-v1.mp4", "https://supabase/video-v2.mp4",
        ])

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])
        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.raw_video_url == "https://supabase/video-v2.mp4"
        assert toon.final_video_url == "https://supabase/video-v2.mp4"
        assert toon.previous_video_urls == ["https://supabase/video-v1.mp4"]
        session.close()

        paths_used = {call.args[1] for call in mock_upload.call_args_list}
        assert len(paths_used) == 2, "each generation must upload to its own unique path"

    def test_generate_omni_video_called_with_native_audio_and_element(self, db, seeded, mocker):
        mock_provider = _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        call = mock_provider.return_value.generate_omni_video.call_args
        contents, settings = call.args
        assert settings["audio"] == "native"
        assert settings["multi_shot"] is True
        assert any(c["type"] == "element" and c["element_id"] == "elem-1" for c in contents)
        prompt_item = next(c for c in contents if c["type"] == "prompt")
        assert "@Mom" in prompt_item["text"]
        assert "shot 1," in prompt_item["text"]


class TestGenerateVideoForToonFailures:
    def test_missing_shots_marks_failed(self, db, seeded, mocker):
        session = db()
        script = session.query(ToonScript).filter_by(character_variant_id=uuid.UUID(seeded["variant_id"])).first()
        script.shots = None
        session.commit()
        session.close()

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "shot data" in toon.generation_error
        session.close()

    def test_element_not_ready_marks_failed(self, db, seeded, mocker):
        session = db()
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.element_status = "unregistered"
        session.commit()
        session.close()

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "Kling element" in toon.generation_error
        session.close()

    def test_kling_error_marks_failed_with_message(self, db, seeded, mocker):
        from app.media.kling_omni import KlingOmniError
        mock_provider = mocker.patch("app.media.kling_omni.KlingOmniProvider")
        mock_provider.return_value.generate_omni_video.side_effect = KlingOmniError("content risk control triggered")

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "content risk control triggered" in toon.generation_error
        session.close()


class TestMultiCharacterGeneration:
    def test_sends_one_element_per_cast_member_and_alternates_dsl_speaker(self, db, seeded_two_variants, mocker):
        mock_provider = _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon(seeded_two_variants["user_id"], seeded_two_variants["toon_id"])

        call = mock_provider.return_value.generate_omni_video.call_args
        contents, _settings = call.args
        element_ids = {c["element_id"] for c in contents if c["type"] == "element"}
        assert element_ids == {"elem-kumar", "elem-wife"}

        prompt_item = next(c for c in contents if c["type"] == "prompt")
        assert "shot 1, 4, @Wife," in prompt_item["text"]
        assert "shot 2, 4, @Kumar," in prompt_item["text"]

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded_two_variants["toon_id"])).first()
        assert toon.status == "ready"
        session.close()

    def test_one_unregistered_character_marks_failed(self, db, seeded_two_variants, mocker):
        session = db()
        wife = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded_two_variants["wife_id"])).first()
        wife.element_status = "unregistered"
        session.commit()
        session.close()

        generate_video_for_toon(seeded_two_variants["user_id"], seeded_two_variants["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded_two_variants["toon_id"])).first()
        assert toon.status == "failed"
        assert "Wife" in toon.generation_error
        session.close()

    def test_too_many_characters_marks_failed(self, db, seeded_two_variants, mocker):
        session = db()
        script = session.query(ToonScript).filter_by(brand_id=uuid.UUID(seeded_two_variants["brand_id"])).first()
        # Pad past MAX_CHARACTERS_PER_VIDEO with duplicate-looking ids -- the
        # count check happens before any DB lookup, so these don't need to
        # resolve to real rows.
        script.character_variant_ids = [str(uuid.uuid4()) for _ in range(5)]
        session.commit()
        session.close()

        generate_video_for_toon(seeded_two_variants["user_id"], seeded_two_variants["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded_two_variants["toon_id"])).first()
        assert toon.status == "failed"
        assert "Kling supports at most" in toon.generation_error
        session.close()


class TestElevenLabsOptIn:
    def test_no_key_configured_falls_back_to_kling_native(self, db, seeded, mocker):
        session = db()
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.voice_provider = "elevenlabs"
        variant.elevenlabs_voice_id = "voice-1"
        session.commit()
        session.close()

        mock_provider = _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        # Brand has no elevenlabs_api_key_encrypted set -> fails open to Kling native.
        settings = mock_provider.return_value.generate_omni_video.call_args.args[1]
        assert settings["audio"] == "native"

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "ready"
        session.close()

    def test_key_configured_uses_off_audio_and_dubs(self, db, seeded, mocker):
        from app.social.crypto import encrypt

        session = db()
        brand = session.query(CharacterBrand).filter_by(id=uuid.UUID(seeded["brand_id"])).first()
        brand.elevenlabs_api_key_encrypted = encrypt("sk-real-key")
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.voice_provider = "elevenlabs"
        variant.elevenlabs_voice_id = "voice-1"
        session.commit()
        session.close()

        mock_provider = _mock_kling_success(mocker)
        mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")
        mock_dub = mocker.patch(
            "app.services.culturetoon_video._dub_dialogue",
            side_effect=lambda tmp_dir, video_path, shots, api_key, voice_id: video_path,
        )

        generate_video_for_toon(seeded["user_id"], seeded["toon_id"])

        settings = mock_provider.return_value.generate_omni_video.call_args.args[1]
        assert settings["audio"] == "off"
        mock_dub.assert_called_once()
        assert mock_dub.call_args.args[3] == "sk-real-key"  # decrypted correctly
        assert mock_dub.call_args.args[4] == "voice-1"
