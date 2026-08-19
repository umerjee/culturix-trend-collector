"""Tests for app/services/culturetoon_selfhosted_video.py — prompt building
from a ToonScript's shots, the cast LoRA-readiness gate, and (TestGenerate
VideoForToonSelfhosted below) the interactive-button orchestrator against
an existing Toon, mirroring tests/test_culturetoon_video.py's in-memory
SQLite/mocked-provider shape for the Kling counterpart."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character_brand import CharacterBrand
from app.models.character import Character
from app.models.character_variant import CharacterVariant
from app.models.toon_script import ToonScript
from app.models.toon import Toon
from app.models.generation_usage import GenerationUsage
from app.services.culturetoon_selfhosted_video import (
    build_prompt_from_script, resolve_ready_lora, generate_toon_video_selfhosted,
    generate_video_for_toon_selfhosted, SelfHostedVideoGenerationError,
)


def _script(mocker, hook_line=None, shots=None, total_duration_seconds=None):
    s = mocker.Mock()
    s.hook_line = hook_line
    s.shots = shots or []
    s.total_duration_seconds = total_duration_seconds
    return s


def _variant(mocker, name="Kumar", lora_status="ready", lora_path="loras/kumar.safetensors"):
    v = mocker.Mock()
    v.name = name
    v.lora_status = lora_status
    v.lora_path = lora_path
    return v


class TestBuildPromptFromScript:
    def test_combines_hook_action_and_dialogue(self, mocker):
        script = _script(
            mocker, hook_line="When mom finds out",
            shots=[
                {"action": "storms into the kitchen", "dialogue": "You didn't eat?!"},
                {"action": "already reaching for a pan", "dialogue": None},
            ],
        )
        prompt = build_prompt_from_script(script)
        assert "When mom finds out" in prompt
        assert "storms into the kitchen" in prompt
        assert 'saying "You didn\'t eat?!"' in prompt
        assert "already reaching for a pan" in prompt

    def test_no_content_falls_back_to_generic_prompt(self, mocker):
        script = _script(mocker, hook_line=None, shots=[])
        assert build_prompt_from_script(script) == "A character reacts to their day."


class TestResolveReadyLora:
    def test_returns_primary_variant_lora_path_when_all_ready(self, mocker):
        variants = [_variant(mocker, name="A"), _variant(mocker, name="B")]
        assert resolve_ready_lora(variants) == variants[0].lora_path

    def test_raises_when_any_variant_not_ready(self, mocker):
        variants = [_variant(mocker, name="A"), _variant(mocker, name="B", lora_status="training")]
        with pytest.raises(SelfHostedVideoGenerationError, match="B"):
            resolve_ready_lora(variants)

    def test_raises_when_lora_status_failed(self, mocker):
        variants = [_variant(mocker, lora_status="failed")]
        with pytest.raises(SelfHostedVideoGenerationError):
            resolve_ready_lora(variants)


class TestGenerateToonVideoSelfhosted:
    def test_raises_before_calling_runpod_when_cast_not_ready(self, mocker):
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job")
        script = _script(mocker, hook_line="hi", shots=[])
        variants = [_variant(mocker, lora_status="none")]
        with pytest.raises(SelfHostedVideoGenerationError):
            generate_toon_video_selfhosted(script, variants, "endpoint-1")
        mock_run.assert_not_called()

    def test_full_success_path(self, mocker):
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job", return_value=b"video-bytes")

        script = _script(mocker, hook_line="hi", shots=[], total_duration_seconds=8)
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1")
        assert result == b"video-bytes"
        mock_run.assert_called_once_with("endpoint-1", {"1": {}})

    def test_use_allocation_retry_routes_through_the_retrying_client_call(self, mocker):
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mock_plain = mocker.patch("app.media.runpod_serverless_client.run_inference_job")
        mock_retry = mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job_with_allocation_retry",
            return_value=b"video-bytes",
        )

        script = _script(mocker, hook_line="hi", shots=[], total_duration_seconds=8)
        variants = [_variant(mocker)]
        result = generate_toon_video_selfhosted(script, variants, "endpoint-1", use_allocation_retry=True)

        assert result == b"video-bytes"
        mock_retry.assert_called_once_with("endpoint-1", {"1": {}})
        mock_plain.assert_not_called()


_SHOTS = [{"shot_number": 1, "duration_seconds": 4, "action": "waves", "expression": "Happy", "dialogue": None}]


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        ToonScript.__table__, Toon.__table__, GenerationUsage.__table__,
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
        lora_status="ready", lora_path="mom.safetensors",
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


class TestGenerateVideoForToonSelfhosted:
    def test_success_path(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry", return_value=b"video-bytes")
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/video.mp4")

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "ready"
        assert toon.video_provider == "self_hosted"
        assert toon.raw_video_url == "https://supabase/video.mp4"
        assert toon.final_video_url == "https://supabase/video.mp4"
        mock_upload.assert_called_once()

        usage = session.query(GenerationUsage).filter_by(toon_id=uuid.UUID(seeded["toon_id"])).all()
        assert len(usage) == 1
        assert usage[0].provider == "runpod_ltx"

    def test_regenerating_archives_the_previous_take(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry", return_value=b"take-2")
        mocker.patch("app.media.storage.upload", return_value="https://supabase/take-2.mp4")

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        toon.raw_video_url = "https://supabase/take-1.mp4"
        toon.final_video_url = "https://supabase/take-1.mp4"
        session.commit()
        session.close()

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.final_video_url == "https://supabase/take-2.mp4"
        assert toon.previous_video_urls == ["https://supabase/take-1.mp4"]

    def test_missing_endpoint_id_marks_toon_failed(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {}, clear=False)
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": ""})
        mock_run = mocker.patch("app.media.runpod_serverless_client.run_inference_job_with_allocation_retry")

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "RUNPOD_SERVERLESS_ENDPOINT_ID" in toon.generation_error
        mock_run.assert_not_called()

    def test_lora_not_ready_marks_toon_failed_and_still_records_usage(self, db, seeded, mocker):
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        session = db()
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(seeded["variant_id"])).first()
        variant.lora_status = "training"
        session.commit()
        session.close()

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "trained LoRA" in toon.generation_error
        # A failed generation still gets a usage row recorded (same
        # philosophy as the batch runner) — cost is 0-duration here since
        # generation never actually started, but the row itself exists.
        usage = session.query(GenerationUsage).filter_by(toon_id=uuid.UUID(seeded["toon_id"])).all()
        assert len(usage) == 1

    def test_runpod_failure_marks_toon_failed(self, db, seeded, mocker):
        from app.media.runpod_serverless_client import RunPodServerlessError
        mocker.patch.dict("os.environ", {"RUNPOD_SERVERLESS_ENDPOINT_ID": "endpoint-1"})
        mocker.patch("app.media.ltx_workflow.build_workflow", return_value={"1": {}})
        mocker.patch(
            "app.media.runpod_serverless_client.run_inference_job_with_allocation_retry",
            side_effect=RunPodServerlessError("worker allocation timed out"),
        )

        generate_video_for_toon_selfhosted(seeded["user_id"], seeded["toon_id"])

        session = db()
        toon = session.query(Toon).filter_by(id=uuid.UUID(seeded["toon_id"])).first()
        assert toon.status == "failed"
        assert "worker allocation timed out" in toon.generation_error
