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

    def test_create_with_target_platforms(self, db, user_id):
        created = culturetoons.create_brand({
            "user_id": user_id, "name": "Funny Clips", "target_platforms": ["tiktok", "instagram"],
        })
        assert created["target_platforms"] == ["tiktok", "instagram"]

    def test_create_without_target_platforms_defaults_empty(self, db, user_id):
        created = culturetoons.create_brand({"user_id": user_id, "name": "Funny Clips"})
        assert created["target_platforms"] == []

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

    def test_new_character_defaults_to_cartoon_3d_art_style(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        character = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "X"})
        assert character["art_style"] == culturetoons.DEFAULT_ART_STYLE

    def test_create_character_rejects_unknown_art_style(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_character({
                "user_id": user_id, "brand_id": brand["id"], "name": "X", "art_style": "oil_painting",
            })
        assert exc_info.value.status_code == 400

    def test_generate_image_prompt_forces_cartoon_style_and_forbids_photorealism(
        self, db, user_id, brand_and_character, mocker,
    ):
        from app.media.base import MediaResult
        brand, character, _variant = brand_and_character
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/char-gen.png")

        culturetoons.generate_character_image(character["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "description": "A middle class man, modern look and well groomed",
            "art_style": "anime",
        })

        sent_prompt = mock_generate.call_args[0][0]
        assert "anime" in sent_prompt.lower()
        assert "not a photorealistic photo" in sent_prompt.lower()
        assert "A middle class man" in sent_prompt

        listed = culturetoons.list_characters(user_id, brand["id"], active_only=False)
        updated = next(c for c in listed if c["id"] == character["id"])
        assert updated["art_style"] == "anime"


class TestVariantImageGeneration:
    def test_generate_image_requires_description(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_variant_image(variant["id"], {"user_id": user_id, "brand_id": brand["id"]})
        assert exc_info.value.status_code == 400

    def test_generate_image_falls_back_to_character_portrait_with_expansion(self, db, user_id, brand_and_character, mocker):
        # Confirmed live, repeatedly: a variant with no photo of its own
        # DOES need to ground on the base character's portrait for roster
        # consistency (the product's video scenarios depend on the family
        # visibly belonging together) -- but only works with (1) the
        # "recasting" prompt framing (preserve_identity=False), not a bare
        # "ignore identity" instruction, and (2) an LLM-expanded concrete
        # visual description, not the user's raw relational text.
        from app.media.base import MediaResult
        brand, character, variant = brand_and_character
        session = db()
        row = session.query(Character).filter_by(id=uuid.UUID(character["id"])).first()
        row.base_image_url = "https://supabase/char-portrait.png"
        session.commit()
        session.close()

        mock_expand = mocker.patch(
            "app.routers.culturetoons._expand_variant_visual_description",
            return_value="A woman in her 30s with warm skin tone, oval face, long dark wavy hair, elegant attire.",
        )
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/variant-gen.png")

        result = culturetoons.generate_variant_image(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"], "description": "Kumar's wife, warm and stylish",
        })

        assert result["image_url"] == "https://supabase/variant-gen.png"
        mock_expand.assert_called_once()
        _, kwargs = mock_generate.call_args
        assert kwargs["reference_image_url"] == "https://supabase/char-portrait.png"
        sent_prompt = mock_generate.call_args[0][0]
        assert "recasting" in sent_prompt.lower()
        assert "warm skin tone, oval face" in sent_prompt

    def test_generate_image_uses_own_reference_when_present(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, character, variant = brand_and_character
        session = db()
        char_row = session.query(Character).filter_by(id=uuid.UUID(character["id"])).first()
        char_row.base_image_url = "https://supabase/char-portrait.png"
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.reference_image_url = "https://supabase/variant-own-ref.png"
        session.commit()
        session.close()

        mock_expand = mocker.patch("app.routers.culturetoons._expand_variant_visual_description")
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/variant-gen.png")

        culturetoons.generate_variant_image(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"], "description": "Kumar's wife",
        })

        # A variant's own photo means it IS that person — no need to
        # expand/override, and identity should be preserved, not recast.
        mock_expand.assert_not_called()
        _, kwargs = mock_generate.call_args
        assert kwargs["reference_image_url"] == "https://supabase/variant-own-ref.png"
        sent_prompt = mock_generate.call_args[0][0]
        assert "match facial identity" in sent_prompt.lower()

    def test_expand_variant_visual_description_falls_back_on_provider_failure(self, db, user_id, brand_and_character, mocker):
        brand, character, variant = brand_and_character
        mocker.patch.dict("os.environ", {"QWEN_API_KEY": "fake-key"})
        mocker.patch("openai.OpenAI").return_value.chat.completions.create.side_effect = RuntimeError("provider down")

        session = db()
        char_row = session.query(Character).filter_by(id=uuid.UUID(character["id"])).first()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()

        result = culturetoons._expand_variant_visual_description(char_row, variant_row, "she is the wife")
        assert result == "she is the wife"
        session.close()

    def test_generate_image_includes_culture_tag_in_prompt(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, _character, variant = brand_and_character
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/variant-gen.png")

        result = culturetoons.generate_variant_image(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "description": "A relative of the main character", "culture_tag": "chinese",
        })

        assert result["culture_tag"] == "chinese"
        sent_prompt = mock_generate.call_args[0][0]
        assert "chinese" in sent_prompt.lower()

    def test_upload_variant_reference_image_does_not_touch_image_url(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        mocker.patch("app.media.storage.upload", return_value="https://supabase/variant-ref.png")

        result = _run(culturetoons.upload_variant_reference_image(
            variant["id"], user_id=user_id, brand_id=brand["id"],
            file=_FakeUploadFile(b"fake-png", "image/png"),
        ))
        assert result["reference_image_url"] == "https://supabase/variant-ref.png"
        assert result["image_url"] is None


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

    def test_suggest_unknown_source_404s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 999999,
                "character_variant_id": variant["id"],
            })
        assert exc_info.value.status_code == 404

    def test_suggest_requires_character_variant(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 1,
            })
        assert exc_info.value.status_code == 400

    def test_suggest_out_of_range_duration_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 1,
                "character_variant_id": variant["id"], "target_duration_seconds": 999,
            })
        assert exc_info.value.status_code == 400

    def test_suggest_out_of_range_num_shots_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 1,
                "character_variant_id": variant["id"], "num_shots": 99,
            })
        assert exc_info.value.status_code == 400

    def test_suggest_with_multiple_character_variant_ids(self, db, user_id, brand_and_character, mocker):
        brand, character, variant = brand_and_character
        variant2 = culturetoons.create_variant({
            "user_id": user_id, "brand_id": brand["id"], "character_id": character["id"], "name": "Wife",
        })
        session = db()
        persona = Persona(name="Reality TV Stan", description="loves drama", motivations="gossip", interests="tv")
        session.add(persona)
        session.commit()
        persona_id = persona.id
        session.close()

        fake_shots = [
            {"shot_number": 1, "duration_seconds": 4, "action": "a", "expression": None, "dialogue": None, "speaker_variant_id": variant["id"]},
        ]
        # Captures names at call time rather than holding onto the ORM
        # objects themselves — suggest_script's own later session.commit()
        # expires them (expire_on_commit=True), and the session is closed
        # by the time this test would otherwise touch .name, raising
        # DetachedInstanceError.
        captured_names = []

        def _capture(*args, **kwargs):
            captured_names.extend(v.name for v in args[1])
            return {"hook_line": "H", "tone": "funny", "shots": fake_shots, "total_duration_seconds": 4}

        mock_generate = mocker.patch(
            "app.services.culturetoon_script.generate_toon_script",
            side_effect=_capture,
        )
        result = culturetoons.suggest_script({
            "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": persona_id,
            "character_variant_ids": [variant["id"], variant2["id"]], "tone": "funny",
        })

        assert result["character_variant_id"] == variant["id"]
        assert set(result["character_variant_ids"]) == {variant["id"], variant2["id"]}
        assert mock_generate.called
        assert set(captured_names) == {"Indian Mom", "Wife"}

    def test_suggest_exceeds_max_characters_400s(self, db, user_id, brand_and_character):
        brand, character, variant = brand_and_character
        extra_ids = [variant["id"]]
        for i in range(4):
            v = culturetoons.create_variant({
                "user_id": user_id, "brand_id": brand["id"], "character_id": character["id"], "name": f"Extra {i}",
            })
            extra_ids.append(v["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 1,
                "character_variant_ids": extra_ids,
            })
        assert exc_info.value.status_code == 400

    def test_suggest_unowned_variant_in_cast_404s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        other_user = str(uuid.uuid4())
        other_brand = culturetoons.create_brand({"user_id": other_user})
        other_character = culturetoons.create_character({"user_id": other_user, "brand_id": other_brand["id"], "name": "Other"})
        other_variant = culturetoons.create_variant({
            "user_id": other_user, "brand_id": other_brand["id"], "character_id": other_character["id"], "name": "Stranger",
        })
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script({
                "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 1,
                "character_variant_ids": [variant["id"], other_variant["id"]],
            })
        assert exc_info.value.status_code == 404

    def test_delete_archives_not_deletes(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        culturetoons.delete_script(script["id"], user_id, brand["id"])
        archived = culturetoons.get_script(script["id"], user_id, brand["id"])
        assert archived["status"] == "archived"


class TestSuggestScriptFromIdea:
    def test_requires_idea(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script_from_idea({
                "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            })
        assert exc_info.value.status_code == 400

    def test_invalid_tone_400s(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script_from_idea({
                "user_id": user_id, "brand_id": brand["id"], "idea": "Character reacts to a trend", "tone": "nope",
            })
        assert exc_info.value.status_code == 400

    def test_generates_shot_structured_script_from_free_text_idea(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        fake_shots = [
            {"shot_number": 1, "duration_seconds": 5, "action": "sees the mess", "expression": "Shocked", "dialogue": "Who did this?!"},
            {"shot_number": 2, "duration_seconds": 3, "action": "sighs", "expression": "Deadpan", "dialogue": None},
        ]
        mock_generate = mocker.patch(
            "app.services.culturetoon_script.generate_toon_script_from_idea",
            return_value={"hook_line": "H", "tone": "funny", "shots": fake_shots, "total_duration_seconds": 8},
        )
        result = culturetoons.suggest_script_from_idea({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            "idea": "The character comes home to find the kitchen destroyed", "tone": "funny",
        })

        assert result["generation_source"] == "ai"
        assert result["source_type"] == "idea"
        assert result["source_id"] is None
        assert result["shots"] == fake_shots
        mock_generate.assert_called_once()
        call_args = mock_generate.call_args
        assert call_args[0][0] == "The character comes home to find the kitchen destroyed"

    def test_generation_failure_returns_502(self, db, user_id, brand_and_character, mocker):
        from app.services.culturetoon_script import ToonScriptGenerationError
        brand, _character, variant = brand_and_character
        mocker.patch(
            "app.services.culturetoon_script.generate_toon_script_from_idea",
            side_effect=ToonScriptGenerationError("provider down"),
        )
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script_from_idea({
                "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"], "idea": "Something",
            })
        assert exc_info.value.status_code == 502

    def test_requires_character_variant(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script_from_idea({"user_id": user_id, "brand_id": brand["id"], "idea": "Something"})
        assert exc_info.value.status_code == 400

    def test_out_of_range_duration_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_script_from_idea({
                "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
                "idea": "Something", "target_duration_seconds": 1,
            })
        assert exc_info.value.status_code == 400


class TestGenerateScriptBackground:
    def test_requires_scene_information(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"], "hook_line": "Hook",
        })
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_script_background(script["id"], {"user_id": user_id, "brand_id": brand["id"]})
        assert exc_info.value.status_code == 400

    def test_generates_from_manual_scene_direction(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            "scene_direction": "A cluttered suburban kitchen at dinnertime.",
        })
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/bg-gen.png")

        result = culturetoons.generate_script_background(script["id"], {"user_id": user_id, "brand_id": brand["id"]})

        assert result["image_url"] == "https://supabase/bg-gen.png"
        assert "cluttered suburban kitchen" in result["description"]
        sent_prompt = mock_generate.call_args[0][0]
        assert "no people, no characters" in sent_prompt.lower()
        assert "cluttered suburban kitchen" in sent_prompt

        updated_script = culturetoons.get_script(script["id"], user_id, brand["id"])
        assert updated_script["background_id"] == result["id"]

    def test_generates_from_shot_actions_when_no_scene_direction(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, _character, variant = brand_and_character
        session = db()
        from app.models.toon_script import ToonScript
        script_row = ToonScript(
            brand_id=uuid.UUID(brand["id"]), character_variant_id=uuid.UUID(variant["id"]),
            generation_source="ai",
            shots=[
                {"shot_number": 1, "duration_seconds": 4, "action": "She storms into a busy office."},
                {"shot_number": 2, "duration_seconds": 4, "action": "Cut to a rooftop at sunset."},
            ],
        )
        session.add(script_row)
        session.commit()
        script_id = str(script_row.id)
        session.close()

        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/bg-gen.png")

        culturetoons.generate_script_background(script_id, {"user_id": user_id, "brand_id": brand["id"]})

        sent_prompt = mock_generate.call_args[0][0]
        assert "busy office" in sent_prompt
        assert "rooftop at sunset" in sent_prompt

    def test_extra_description_combines_with_scene(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            "scene_direction": "A kitchen.",
        })
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/bg-gen.png")

        culturetoons.generate_script_background(script["id"], {
            "user_id": user_id, "brand_id": brand["id"], "extra_description": "rainy evening, moody lighting",
        })

        sent_prompt = mock_generate.call_args[0][0]
        assert "kitchen" in sent_prompt
        assert "rainy evening, moody lighting" in sent_prompt

    def test_created_background_is_reusable_in_brands_pool(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            "scene_direction": "A kitchen.",
        })
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/bg-gen.png")

        culturetoons.generate_script_background(script["id"], {"user_id": user_id, "brand_id": brand["id"]})

        listed = culturetoons.list_backgrounds(user_id, brand["id"])
        assert len(listed) == 1


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
