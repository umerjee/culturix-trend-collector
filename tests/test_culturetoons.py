"""Tests for CultureToons (app/routers/culturetoons.py) — matches this
codebase's established test convention (see tests/test_shopify_reels.py):
in-memory SQLite, mocked external calls (LLM providers, Supabase upload),
router functions called directly rather than through a full ASGI TestClient
— calling functions directly avoids ever importing app.main (whose
lifespan() runs real DDL against the *actual* DATABASE_URL from .env if
triggered), the same reason tests/test_clip_generation.py calls
app.routers.clips functions directly instead of going through the app.
"""
import asyncio
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character_brand import CharacterBrand
from app.models.character import Character
from app.models.character_variant import CharacterVariant
from app.models.expression import Expression
from app.models.toon_background import ToonBackground
from app.models.toon_script import ToonScript
from app.models.toon import Toon
from app.models.persona import Persona
from app.models.cluster import Cluster
from app.routers import culturetoons


class _FakeUploadFile:
    def __init__(self, data: bytes, content_type: str):
        self._data = data
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        Expression.__table__, ToonBackground.__table__, ToonScript.__table__,
        Toon.__table__, Persona.__table__, Cluster.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


@pytest.fixture
def user_id():
    return str(uuid.uuid4())


@pytest.fixture
def brand_and_character(db, user_id):
    brand = culturetoons.create_brand({"user_id": user_id, "name": "Test Brand"})
    character = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Base Character"})
    variant = culturetoons.create_variant({
        "user_id": user_id, "brand_id": brand["id"], "character_id": character["id"],
        "name": "Indian Mom", "culture_tag": "indian",
    })
    return brand, character, variant


class TestBrand:
    def test_create_and_list(self, db, user_id):
        created = culturetoons.create_brand({"user_id": user_id, "name": "Funny Clips"})
        assert created["name"] == "Funny Clips"
        assert created["has_elevenlabs_key"] is False

        listed = culturetoons.list_brands(user_id)
        assert len(listed) == 1
        assert listed[0]["id"] == created["id"]

    def test_multiple_brands_per_user(self, db, user_id):
        b1 = culturetoons.create_brand({"user_id": user_id, "name": "Funny Clips"})
        b2 = culturetoons.create_brand({"user_id": user_id, "name": "Baby Videos"})
        assert b1["id"] != b2["id"]
        listed = culturetoons.list_brands(user_id)
        assert {b["id"] for b in listed} == {b1["id"], b2["id"]}

    def test_get_brand_404_when_missing(self, db, user_id):
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.get_brand(str(uuid.uuid4()), user_id)
        assert exc_info.value.status_code == 404

    def test_update_brand_encrypts_elevenlabs_key(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        updated = culturetoons.update_brand(brand["id"], {
            "user_id": user_id, "elevenlabs_api_key": "sk-real-key-value",
        })
        assert updated["has_elevenlabs_key"] is True
        # Never return the plaintext or ciphertext key in the serialized response.
        assert "elevenlabs_api_key" not in updated
        assert "elevenlabs_api_key_encrypted" not in updated


class TestMultiBrand:
    def test_brands_dont_collide(self, db, user_id):
        b1 = culturetoons.create_brand({"user_id": user_id, "name": "Funny Clips"})
        b2 = culturetoons.create_brand({"user_id": user_id, "name": "Baby Videos"})
        c1 = culturetoons.create_character({"user_id": user_id, "brand_id": b1["id"], "name": "Char A"})
        c2 = culturetoons.create_character({"user_id": user_id, "brand_id": b2["id"], "name": "Char B"})

        assert [c["id"] for c in culturetoons.list_characters(user_id, b1["id"])] == [c1["id"]]
        assert [c["id"] for c in culturetoons.list_characters(user_id, b2["id"])] == [c2["id"]]

    def test_cross_brand_lookup_404s(self, db, user_id):
        b1 = culturetoons.create_brand({"user_id": user_id, "name": "Funny Clips"})
        b2 = culturetoons.create_brand({"user_id": user_id, "name": "Baby Videos"})
        character = culturetoons.create_character({"user_id": user_id, "brand_id": b1["id"], "name": "Char A"})

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_character(character["id"], {"user_id": user_id, "brand_id": b2["id"], "name": "X"})
        assert exc_info.value.status_code == 404


class TestCharactersRequireBrand:
    def test_create_character_with_unknown_brand_404s(self, db, user_id):
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_character({"user_id": user_id, "brand_id": str(uuid.uuid4()), "name": "X"})
        assert exc_info.value.status_code == 404

    def test_create_and_list_character(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        character = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Base Character"})
        assert character["name"] == "Base Character"

        listed = culturetoons.list_characters(user_id, brand["id"])
        assert len(listed) == 1
        assert listed[0]["id"] == character["id"]

    def test_update_character(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        character = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Base Character"})
        updated = culturetoons.update_character(character["id"], {
            "user_id": user_id, "brand_id": brand["id"], "description": "desc",
        })
        assert updated["description"] == "desc"


class TestCharacterImageGeneration:
    def test_generate_image_requires_description(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_character_image(character["id"], {"user_id": user_id, "brand_id": brand["id"]})
        assert exc_info.value.status_code == 400

    def test_generate_image_persists_description_and_sets_base_image(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, character, _variant = brand_and_character
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-jpeg", content_type="image/jpeg"),
        )
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/char-gen.jpg")

        result = culturetoons.generate_character_image(character["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "description": "A tall Indian mother in a bright green saree, warm smile, cartoon style",
        })

        assert result["description"].startswith("A tall Indian mother")
        assert result["base_image_url"] == "https://supabase/char-gen.jpg"
        mock_generate.assert_called_once()
        _, kwargs = mock_generate.call_args
        assert kwargs["reference_image_url"] is None
        mock_upload.assert_called_once()
        # jpeg content type from Cloudflare's provider must not be rejected
        # (save_image()'s PNG/WebP-only allowlist doesn't apply here).
        assert mock_upload.call_args[0][2] == "image/jpeg"

    def test_generate_image_passes_reference_image_url(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, character, _variant = brand_and_character
        session = db()
        row = session.query(Character).filter_by(id=uuid.UUID(character["id"])).first()
        row.reference_image_url = "https://supabase/char-ref.png"
        row.description = "Existing description"
        session.commit()
        session.close()

        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/char-gen.png")

        culturetoons.generate_character_image(character["id"], {"user_id": user_id, "brand_id": brand["id"]})

        _, kwargs = mock_generate.call_args
        assert kwargs["reference_image_url"] == "https://supabase/char-ref.png"

    def test_generate_image_failure_returns_502(self, db, user_id, brand_and_character, mocker):
        brand, character, _variant = brand_and_character
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            side_effect=RuntimeError("provider down"),
        )
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_character_image(character["id"], {
                "user_id": user_id, "brand_id": brand["id"], "description": "A character",
            })
        assert exc_info.value.status_code == 502

    def test_upload_reference_image_does_not_touch_base_image(self, db, user_id, brand_and_character, mocker):
        brand, character, _variant = brand_and_character
        mocker.patch("app.media.storage.upload", return_value="https://supabase/char-ref.png")

        result = _run(culturetoons.upload_character_reference_image(
            character["id"], user_id=user_id, brand_id=brand["id"],
            file=_FakeUploadFile(b"fake-png", "image/png"),
        ))
        assert result["reference_image_url"] == "https://supabase/char-ref.png"
        assert result["base_image_url"] is None


class TestVariantsAndExpressions:
    def test_create_variant_and_upload_expression_image(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/expr.png")

        result = _run(culturetoons.upload_expression_image(
            variant["id"], "Angry", user_id=user_id, brand_id=brand["id"],
            file=_FakeUploadFile(b"fake-png", "image/png"),
        ))
        assert result["name"] == "Angry"
        assert result["image_url"] == "https://supabase/expr.png"
        mock_upload.assert_called_once()

        _run(culturetoons.upload_expression_image(
            variant["id"], "Angry", user_id=user_id, brand_id=brand["id"],
            file=_FakeUploadFile(b"fake-png-2", "image/png"),
        ))
        expressions = culturetoons.list_expressions(variant["id"], user_id, brand["id"])
        assert len(expressions) == 1

    def test_invalid_expression_name_rejected(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            _run(culturetoons.upload_expression_image(
                variant["id"], "Bored", user_id=user_id, brand_id=brand["id"],
                file=_FakeUploadFile(b"x", "image/png"),
            ))
        assert exc_info.value.status_code == 400

    def test_expression_unique_constraint_enforced_at_db_level(self, db, brand_and_character):
        _brand, _character, variant = brand_and_character
        session = db()
        session.add(Expression(character_variant_id=uuid.UUID(variant["id"]), name="Happy"))
        session.commit()
        session.add(Expression(character_variant_id=uuid.UUID(variant["id"]), name="Happy"))
        with pytest.raises(Exception):
            session.commit()
        session.close()

    def test_upload_rejects_disallowed_content_type(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            _run(culturetoons.upload_variant_image(
                variant["id"], user_id=user_id, brand_id=brand["id"],
                file=_FakeUploadFile(b"not-an-image", "text/plain"),
            ))
        assert exc_info.value.status_code == 400

    def test_cross_user_access_is_404(self, db, brand_and_character):
        _brand, _character, variant = brand_and_character
        other_user = str(uuid.uuid4())
        other_brand = culturetoons.create_brand({"user_id": other_user})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.get_variant(variant["id"], other_user, other_brand["id"])
        assert exc_info.value.status_code == 404


class TestElementRegistration:
    def test_register_element_requires_image(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        no_image_variant = culturetoons.create_variant({
            "user_id": user_id, "brand_id": brand["id"], "character_id": character["id"], "name": "No Image",
        })
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.register_variant_element(
                no_image_variant["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=None,
            )
        assert exc_info.value.status_code == 400

    def test_register_element_sets_pending_and_backgrounds(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        session = db()
        row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        row.image_url = "https://supabase/variant.png"
        session.commit()
        session.close()

        added_tasks = []

        class _FakeBackgroundTasks:
            def add_task(self, func, **kwargs):
                added_tasks.append((func, kwargs))

        result = culturetoons.register_variant_element(
            variant["id"], {"user_id": user_id, "brand_id": brand["id"]},
            background_tasks=_FakeBackgroundTasks(),
        )
        assert result == {"status": "registration_started"}
        assert len(added_tasks) == 1

        updated = culturetoons.get_variant(variant["id"], user_id, brand["id"])
        assert updated["element_status"] == "pending"


class TestBackgrounds:
    def test_create_list_update_delete(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        bg = culturetoons.create_background({"user_id": user_id, "brand_id": brand["id"], "name": "Kitchen", "tags": "indoor,warm"})
        assert bg["name"] == "Kitchen"

        listed = culturetoons.list_backgrounds(user_id, brand["id"])
        assert len(listed) == 1

        updated = culturetoons.update_background(bg["id"], {"user_id": user_id, "brand_id": brand["id"], "name": "Living Room"})
        assert updated["name"] == "Living Room"

        culturetoons.delete_background(bg["id"], user_id, brand["id"])
        assert culturetoons.list_backgrounds(user_id, brand["id"]) == []
        assert len(culturetoons.list_backgrounds(user_id, brand["id"], active_only=False)) == 1


class TestScripts:
    def test_manual_create(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            "hook_line": "Hook", "dialogue": "Mom: \"ok\"", "scene_direction": "Cut to: dishes.",
        })
        assert script["generation_source"] == "manual"
        assert script["status"] == "draft"

    def test_suggest_generates_shot_structured_ai_script(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        session = db()
        persona = Persona(name="Reality TV Stan", description="loves drama", motivations="gossip", interests="tv")
        session.add(persona)
        session.commit()
        persona_id = persona.id
        session.close()

        fake_shots = [
            {"shot_number": 1, "duration_seconds": 4, "action": "storms in", "expression": "Annoyed", "dialogue": "You didn't eat?!"},
            {"shot_number": 2, "duration_seconds": 4, "action": "softens", "expression": "Smiling", "dialogue": None},
        ]
        mocker.patch(
            "app.services.culturetoon_script.generate_toon_script",
            return_value={"hook_line": "H", "tone": "funny", "shots": fake_shots, "total_duration_seconds": 8},
        )
        result = culturetoons.suggest_script({
            "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": persona_id,
            "character_variant_id": variant["id"], "tone": "funny",
        })
        assert result["generation_source"] == "ai"
        assert result["source_type"] == "persona"
        assert result["source_id"] == persona_id
        assert result["hook_line"] == "H"
        assert result["shots"] == fake_shots
        assert result["total_duration_seconds"] == 8

    def test_suggest_invalid_tone_400s(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 1, "tone": "nope",
            })
        assert exc_info.value.status_code == 400

    def test_suggest_invalid_source_type_400s(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({"user_id": user_id, "brand_id": brand["id"], "source_type": "trend", "source_id": 1})
        assert exc_info.value.status_code == 400

    def test_suggest_unknown_source_404s(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 999999,
            })
        assert exc_info.value.status_code == 404

    def test_delete_archives_not_deletes(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        culturetoons.delete_script(script["id"], user_id, brand["id"])
        archived = culturetoons.get_script(script["id"], user_id, brand["id"])
        assert archived["status"] == "archived"


class TestToons:
    def test_lifecycle(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        bg = culturetoons.create_background({"user_id": user_id, "brand_id": brand["id"], "name": "BG"})

        toon = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_id": variant["id"], "script_id": script["id"],
        })
        assert toon["status"] == "idea"

        ready = culturetoons.update_toon(toon["id"], {
            "user_id": user_id, "brand_id": brand["id"], "background_id": bg["id"],
            "final_video_url": "https://example.com/v.mp4", "status": "ready",
        })
        assert ready["status"] == "ready"
        assert ready["background_id"] == bg["id"]

        posted = culturetoons.update_toon(toon["id"], {
            "user_id": user_id, "brand_id": brand["id"], "status": "posted", "platform": "tiktok",
        })
        assert posted["status"] == "posted"
        assert posted["posted_at"] is not None

        culturetoons.delete_toon(toon["id"], user_id, brand["id"])
        archived = culturetoons.get_toon(toon["id"], user_id, brand["id"])
        assert archived["status"] == "archived"

    def test_generate_video_requires_shot_structured_script(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        # Manual script has no `shots` — generate-video should reject it before backgrounding anything.
        script = culturetoons.create_script({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            "hook_line": "Hook", "dialogue": "line",
        })
        toon = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_id": variant["id"], "script_id": script["id"],
        })

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_toon_video(
                toon["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=_FakeBackgroundTasks(),
            )
        assert exc_info.value.status_code == 400

    def test_generate_video_requires_ready_element(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        session = db()
        script_row = session.query(ToonScript).filter_by(id=uuid.UUID(script["id"])).first()
        script_row.shots = [{"shot_number": 1, "duration_seconds": 4, "action": "waves", "expression": "Happy", "dialogue": None}]
        session.commit()
        session.close()

        toon = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_id": variant["id"], "script_id": script["id"],
        })

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        # variant.element_status defaults to "unregistered" — not ready.
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_toon_video(
                toon["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=_FakeBackgroundTasks(),
            )
        assert exc_info.value.status_code == 400
