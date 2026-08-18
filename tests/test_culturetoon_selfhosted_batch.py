"""Tests for app/services/culturetoon_selfhosted_batch.py — work selection
(approved script + no Toon yet), the brand allowlist gate, and pod
lifecycle guarantees (started once, stopped even on failure)."""
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
from app.models.toon_script import ToonScript
from app.models.toon import Toon
from app.models.generation_usage import GenerationUsage
from app.routers import culturetoons
from app.services.culturetoon_selfhosted_batch import (
    _pilot_brand_ids, find_approved_scripts_without_toon, run_selfhosted_video_batch,
)


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
def user_id():
    return str(uuid.uuid4())


def _make_variant(db, user_id, brand_id, name="Kumar", lora_status="ready"):
    character = culturetoons.create_character({"user_id": user_id, "brand_id": brand_id, "name": name})
    variant_data = culturetoons.create_variant({
        "user_id": user_id, "brand_id": brand_id, "character_id": character["id"], "name": name,
    })
    session = db()
    try:
        variant = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant_data["id"])).first()
        variant.lora_status = lora_status
        variant.lora_path = f"loras/{name}.safetensors"
        session.commit()
        return variant.id
    finally:
        session.close()


def _make_script(db, brand_id, variant_id, status="approved"):
    session = db()
    try:
        script = ToonScript(
            brand_id=brand_id, character_variant_id=variant_id, character_variant_ids=[str(variant_id)],
            hook_line="A funny hook", shots=[{"shot_number": 1, "duration_seconds": 5, "action": "waves"}],
            total_duration_seconds=5, generation_source="ai", status=status,
        )
        session.add(script)
        session.commit()
        session.refresh(script)
        return script.id
    finally:
        session.close()


class TestPilotBrandIds:
    def test_empty_env_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("SELFHOSTED_VIDEO_BRAND_IDS", raising=False)
        assert _pilot_brand_ids() == []

    def test_parses_comma_separated_uuids(self, monkeypatch):
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        monkeypatch.setenv("SELFHOSTED_VIDEO_BRAND_IDS", f"{a}, {b}")
        assert _pilot_brand_ids() == [uuid.UUID(a), uuid.UUID(b)]

    def test_ignores_invalid_entries(self, monkeypatch):
        a = str(uuid.uuid4())
        monkeypatch.setenv("SELFHOSTED_VIDEO_BRAND_IDS", f"{a}, not-a-uuid")
        assert _pilot_brand_ids() == [uuid.UUID(a)]


class TestFindApprovedScriptsWithoutToon:
    def test_approved_script_with_no_toon_is_found(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        variant_id = _make_variant(db, user_id, brand["id"])
        script_id = _make_script(db, uuid.UUID(brand["id"]), variant_id, status="approved")

        session = db()
        try:
            found = find_approved_scripts_without_toon(session, uuid.UUID(brand["id"]))
            assert [s.id for s in found] == [script_id]
        finally:
            session.close()

    def test_approved_script_with_existing_toon_is_excluded(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        variant_id = _make_variant(db, user_id, brand["id"])
        script_id = _make_script(db, uuid.UUID(brand["id"]), variant_id, status="approved")

        session = db()
        try:
            session.add(Toon(
                brand_id=uuid.UUID(brand["id"]), character_variant_id=variant_id, script_id=script_id,
                status="ready",
            ))
            session.commit()
            found = find_approved_scripts_without_toon(session, uuid.UUID(brand["id"]))
            assert found == []
        finally:
            session.close()

    def test_non_approved_script_is_excluded(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        variant_id = _make_variant(db, user_id, brand["id"])
        _make_script(db, uuid.UUID(brand["id"]), variant_id, status="draft")

        session = db()
        try:
            found = find_approved_scripts_without_toon(session, uuid.UUID(brand["id"]))
            assert found == []
        finally:
            session.close()


class TestRunSelfhostedVideoBatch:
    def test_empty_brand_ids_never_starts_the_pod(self, db, monkeypatch, mocker):
        monkeypatch.delenv("SELFHOSTED_VIDEO_BRAND_IDS", raising=False)
        mock_start = mocker.patch("app.media.runpod_client.start_pod")
        run_selfhosted_video_batch()
        mock_start.assert_not_called()

    def test_generates_video_for_approved_script_and_stops_pod(self, db, user_id, monkeypatch, mocker):
        brand = culturetoons.create_brand({"user_id": user_id})
        variant_id = _make_variant(db, user_id, brand["id"])
        script_id = _make_script(db, uuid.UUID(brand["id"]), variant_id, status="approved")
        monkeypatch.setenv("SELFHOSTED_VIDEO_BRAND_IDS", brand["id"])
        monkeypatch.setenv("RUNPOD_POD_ID", "pod-123")

        mock_start = mocker.patch("app.media.runpod_client.start_pod")
        mock_wait = mocker.patch("app.media.runpod_client.wait_for_pod_ready", return_value="http://host:8188")
        mock_stop = mocker.patch("app.media.runpod_client.stop_pod")
        mocker.patch(
            "app.services.culturetoon_selfhosted_video.generate_toon_video_selfhosted",
            return_value=b"video-bytes",
        )
        mocker.patch("app.media.storage.upload", return_value="https://example.com/video.mp4")

        run_selfhosted_video_batch()

        mock_start.assert_called_once_with("pod-123")
        mock_wait.assert_called_once()
        mock_stop.assert_called_once_with("pod-123")

        session = db()
        try:
            toon = session.query(Toon).filter_by(script_id=script_id).first()
            assert toon is not None
            assert toon.status == "ready"
            assert toon.video_provider == "self_hosted"
            assert toon.raw_video_url == "https://example.com/video.mp4"
            usage = session.query(GenerationUsage).filter_by(toon_id=toon.id).first()
            assert usage is not None
            assert usage.provider == "runpod_ltx"
        finally:
            session.close()

    def test_pod_is_stopped_even_when_generation_raises(self, db, user_id, monkeypatch, mocker):
        brand = culturetoons.create_brand({"user_id": user_id})
        variant_id = _make_variant(db, user_id, brand["id"])
        _make_script(db, uuid.UUID(brand["id"]), variant_id, status="approved")
        monkeypatch.setenv("SELFHOSTED_VIDEO_BRAND_IDS", brand["id"])
        monkeypatch.setenv("RUNPOD_POD_ID", "pod-123")

        mocker.patch("app.media.runpod_client.start_pod")
        mocker.patch("app.media.runpod_client.wait_for_pod_ready", side_effect=RuntimeError("pod never came up"))
        mock_stop = mocker.patch("app.media.runpod_client.stop_pod")

        run_selfhosted_video_batch()  # must not raise — top-level try/except logs instead

        mock_stop.assert_called_once_with("pod-123")

    def test_character_not_lora_ready_marks_toon_failed_without_crashing_batch(self, db, user_id, monkeypatch, mocker):
        brand = culturetoons.create_brand({"user_id": user_id})
        variant_id = _make_variant(db, user_id, brand["id"], lora_status="none")
        script_id = _make_script(db, uuid.UUID(brand["id"]), variant_id, status="approved")
        monkeypatch.setenv("SELFHOSTED_VIDEO_BRAND_IDS", brand["id"])
        monkeypatch.setenv("RUNPOD_POD_ID", "pod-123")

        mocker.patch("app.media.runpod_client.start_pod")
        mocker.patch("app.media.runpod_client.wait_for_pod_ready", return_value="http://host:8188")
        mocker.patch("app.media.runpod_client.stop_pod")

        run_selfhosted_video_batch()

        session = db()
        try:
            toon = session.query(Toon).filter_by(script_id=script_id).first()
            assert toon.status == "failed"
            assert "not ready" in toon.generation_error
        finally:
            session.close()

    def test_inactive_brand_is_not_processed(self, db, user_id, monkeypatch, mocker):
        brand = culturetoons.create_brand({"user_id": user_id})
        culturetoons.update_brand(brand["id"], {"user_id": user_id, "is_active": False})
        variant_id = _make_variant(db, user_id, brand["id"])
        _make_script(db, uuid.UUID(brand["id"]), variant_id, status="approved")
        monkeypatch.setenv("SELFHOSTED_VIDEO_BRAND_IDS", brand["id"])
        monkeypatch.setenv("RUNPOD_POD_ID", "pod-123")

        mocker.patch("app.media.runpod_client.start_pod")
        mocker.patch("app.media.runpod_client.wait_for_pod_ready", return_value="http://host:8188")
        mocker.patch("app.media.runpod_client.stop_pod")
        mock_generate = mocker.patch("app.services.culturetoon_selfhosted_video.generate_toon_video_selfhosted")

        run_selfhosted_video_batch()

        mock_generate.assert_not_called()
