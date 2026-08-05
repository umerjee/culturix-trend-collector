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
    culturetoons.upsert_brand({"user_id": user_id, "name": "Test Brand"})
    character = culturetoons.create_character({"user_id": user_id, "name": "Base Character"})
    variant = culturetoons.create_variant({
        "user_id": user_id, "character_id": character["id"],
        "name": "Indian Mom", "culture_tag": "indian",
    })
    return character, variant


class TestBrand:
    def test_upsert_creates_then_updates(self, db, user_id):
        created = culturetoons.upsert_brand({"user_id": user_id, "name": "First Name"})
        assert created["name"] == "First Name"

        updated = culturetoons.upsert_brand({"user_id": user_id, "name": "New Name"})
        assert updated["id"] == created["id"]
        assert updated["name"] == "New Name"

    def test_get_brand_404_when_missing(self, db, user_id):
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.get_brand(user_id)
        assert exc_info.value.status_code == 404


class TestCharactersRequireBrand:
    def test_create_character_without_brand_404s(self, db, user_id):
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_character({"user_id": user_id, "name": "X"})
        assert exc_info.value.status_code == 404

    def test_create_and_list_character(self, db, user_id):
        culturetoons.upsert_brand({"user_id": user_id})
        character = culturetoons.create_character({"user_id": user_id, "name": "Base Character"})
        assert character["name"] == "Base Character"

        listed = culturetoons.list_characters(user_id)
        assert len(listed) == 1
        assert listed[0]["id"] == character["id"]

    def test_update_character(self, db, user_id):
        culturetoons.upsert_brand({"user_id": user_id})
        character = culturetoons.create_character({"user_id": user_id, "name": "Base Character"})
        updated = culturetoons.update_character(character["id"], {"user_id": user_id, "description": "desc"})
        assert updated["description"] == "desc"


class TestVariantsAndExpressions:
    def test_create_variant_and_upload_expression_image(self, db, user_id, brand_and_character, mocker):
        _character, variant = brand_and_character
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/expr.png")

        result = _run(culturetoons.upload_expression_image(
            variant["id"], "Angry", user_id=user_id, file=_FakeUploadFile(b"fake-png", "image/png"),
        ))
        assert result["name"] == "Angry"
        assert result["image_url"] == "https://supabase/expr.png"
        mock_upload.assert_called_once()

        # Re-uploading the same name upserts, not duplicates.
        _run(culturetoons.upload_expression_image(
            variant["id"], "Angry", user_id=user_id, file=_FakeUploadFile(b"fake-png-2", "image/png"),
        ))
        expressions = culturetoons.list_expressions(variant["id"], user_id)
        assert len(expressions) == 1

    def test_invalid_expression_name_rejected(self, db, user_id, brand_and_character):
        _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            _run(culturetoons.upload_expression_image(
                variant["id"], "Bored", user_id=user_id, file=_FakeUploadFile(b"x", "image/png"),
            ))
        assert exc_info.value.status_code == 400

    def test_expression_unique_constraint_enforced_at_db_level(self, db, brand_and_character):
        _character, variant = brand_and_character
        session = db()
        session.add(Expression(character_variant_id=uuid.UUID(variant["id"]), name="Happy"))
        session.commit()
        session.add(Expression(character_variant_id=uuid.UUID(variant["id"]), name="Happy"))
        with pytest.raises(Exception):
            session.commit()
        session.close()

    def test_upload_rejects_disallowed_content_type(self, db, user_id, brand_and_character):
        _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            _run(culturetoons.upload_variant_image(
                variant["id"], user_id=user_id, file=_FakeUploadFile(b"not-an-image", "text/plain"),
            ))
        assert exc_info.value.status_code == 400

    def test_cross_user_access_is_404(self, db, brand_and_character):
        _character, variant = brand_and_character
        other_user = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.get_variant(variant["id"], other_user)
        assert exc_info.value.status_code == 404


class TestBackgrounds:
    def test_create_list_update_delete(self, db, user_id):
        culturetoons.upsert_brand({"user_id": user_id})
        bg = culturetoons.create_background({"user_id": user_id, "name": "Kitchen", "tags": "indoor,warm"})
        assert bg["name"] == "Kitchen"

        listed = culturetoons.list_backgrounds(user_id)
        assert len(listed) == 1

        updated = culturetoons.update_background(bg["id"], {"user_id": user_id, "name": "Living Room"})
        assert updated["name"] == "Living Room"

        culturetoons.delete_background(bg["id"], user_id)
        assert culturetoons.list_backgrounds(user_id) == []
        assert len(culturetoons.list_backgrounds(user_id, active_only=False)) == 1


class TestScripts:
    def test_manual_create(self, db, user_id, brand_and_character):
        _character, variant = brand_and_character
        script = culturetoons.create_script({
            "user_id": user_id, "character_variant_id": variant["id"],
            "hook_line": "Hook", "dialogue": "Mom: \"ok\"", "scene_direction": "Cut to: dishes.",
        })
        assert script["generation_source"] == "manual"
        assert script["status"] == "draft"

    def test_suggest_generates_and_persists_ai_script(self, db, user_id, brand_and_character, mocker):
        _character, variant = brand_and_character
        session = db()
        persona = Persona(name="Reality TV Stan", description="loves drama", motivations="gossip", interests="tv")
        session.add(persona)
        session.commit()
        persona_id = persona.id
        session.close()

        mocker.patch(
            "app.services.culturetoon_script.generate_toon_script",
            return_value={"hook_line": "H", "dialogue": "D", "scene_direction": "S"},
        )
        result = culturetoons.suggest_script({
            "user_id": user_id, "source_type": "persona", "source_id": persona_id,
            "character_variant_id": variant["id"],
        })
        assert result["generation_source"] == "ai"
        assert result["source_type"] == "persona"
        assert result["source_id"] == persona_id
        assert result["hook_line"] == "H"

    def test_suggest_invalid_source_type_400s(self, db, user_id):
        culturetoons.upsert_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({"user_id": user_id, "source_type": "trend", "source_id": 1})
        assert exc_info.value.status_code == 400

    def test_suggest_unknown_source_404s(self, db, user_id):
        culturetoons.upsert_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({"user_id": user_id, "source_type": "persona", "source_id": 999999})
        assert exc_info.value.status_code == 404

    def test_delete_archives_not_deletes(self, db, user_id, brand_and_character):
        _character, variant = brand_and_character
        script = culturetoons.create_script({"user_id": user_id, "character_variant_id": variant["id"]})
        culturetoons.delete_script(script["id"], user_id)
        archived = culturetoons.get_script(script["id"], user_id)
        assert archived["status"] == "archived"


class TestToons:
    def test_lifecycle(self, db, user_id, brand_and_character):
        _character, variant = brand_and_character
        script = culturetoons.create_script({"user_id": user_id, "character_variant_id": variant["id"]})
        bg = culturetoons.create_background({"user_id": user_id, "name": "BG"})

        toon = culturetoons.create_toon({
            "user_id": user_id, "character_variant_id": variant["id"], "script_id": script["id"],
        })
        assert toon["status"] == "idea"

        ready = culturetoons.update_toon(toon["id"], {
            "user_id": user_id, "background_id": bg["id"],
            "final_video_url": "https://example.com/v.mp4", "status": "ready",
        })
        assert ready["status"] == "ready"
        assert ready["background_id"] == bg["id"]

        posted = culturetoons.update_toon(toon["id"], {
            "user_id": user_id, "status": "posted", "platform": "tiktok",
        })
        assert posted["status"] == "posted"
        assert posted["posted_at"] is not None

        culturetoons.delete_toon(toon["id"], user_id)
        archived = culturetoons.get_toon(toon["id"], user_id)
        assert archived["status"] == "archived"
