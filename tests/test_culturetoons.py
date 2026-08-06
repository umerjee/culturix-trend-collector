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
from fastapi import BackgroundTasks, HTTPException
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
from app.models.toon_post import ToonPost
from app.models.toon_episode import ToonEpisode
from app.models.connected_account import ConnectedAccount
from app.models.persona import Persona
from app.models.cluster import Cluster
from app.models.character_relationship import CharacterRelationship
from app.models.generation_usage import GenerationUsage
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
        Toon.__table__, ToonPost.__table__, ToonEpisode.__table__, ConnectedAccount.__table__,
        Persona.__table__, Cluster.__table__,
        CharacterRelationship.__table__, GenerationUsage.__table__,
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

    def test_create_character_auto_creates_default_variant(self, db, user_id):
        # A bare Character has no element_status/kling_element_id of its own
        # — those live only on CharacterVariant — so a character with zero
        # variants has no "Register for video" step reachable anywhere.
        # Confirmed live: this left a real user with a fully-built base
        # character and no way to register it at all. A default variant
        # named after the character removes that dead end.
        brand = culturetoons.create_brand({"user_id": user_id})
        result = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Kumar"})
        assert "default_variant" in result
        assert result["default_variant"]["name"] == "Kumar"
        assert result["default_variant"]["character_id"] == result["id"]

        variants = culturetoons.list_variants(user_id, brand["id"], character_id=result["id"])
        assert len(variants) == 1
        assert variants[0]["id"] == result["default_variant"]["id"]

    def test_update_character(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        character = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Base Character"})
        updated = culturetoons.update_character(character["id"], {
            "user_id": user_id, "brand_id": brand["id"], "description": "desc",
        })
        assert updated["description"] == "desc"

    def test_delete_character_archives_not_deletes(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        character = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Base Character"})
        culturetoons.delete_character(character["id"], user_id, brand["id"])

        assert culturetoons.list_characters(user_id, brand["id"]) == []
        archived = culturetoons.list_characters(user_id, brand["id"], active_only=False)
        assert len(archived) == 1
        assert archived[0]["is_active"] is False


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
        # Confirmed live, repeatedly: a variant with no photo of its own AND
        # no explicit culture_tag (no signal that ethnicity should differ
        # from the base character) DOES need to ground on the base
        # character's portrait for roster consistency (the product's video
        # scenarios depend on the family visibly belonging together) -- but
        # only works with (1) the "recasting" prompt framing
        # (preserve_identity=False), not a bare "ignore identity"
        # instruction, and (2) an LLM-expanded concrete visual description,
        # not the user's raw relational text. See
        # test_culture_tag_drops_reference_image_for_correct_ethnicity for
        # the culture_tag-set case, which behaves differently.
        from app.media.base import MediaResult
        brand, character, variant = brand_and_character
        session = db()
        row = session.query(Character).filter_by(id=uuid.UUID(character["id"])).first()
        row.base_image_url = "https://supabase/char-portrait.png"
        # The fixture variant defaults to culture_tag="indian" — clear it so
        # this test exercises the "no explicit ethnicity signal" path, not
        # the culture_tag-set path covered separately below.
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.culture_tag = None
        session.commit()
        session.close()

        mock_expand = mocker.patch(
            "app.routers.culturetoons._expand_variant_visual_description",
            return_value=("A woman in her 30s with warm skin tone, oval face, long dark wavy hair, elegant attire.", False),
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
        assert result == ("she is the wife", True)
        session.close()

    def test_generate_image_surfaces_warning_when_expansion_degrades(self, db, user_id, brand_and_character, mocker):
        # Confirmed live: when the expansion LLM call fails, generation
        # silently falls back to the user's raw (often vague/relational)
        # description with no ethnicity/attire anchor, producing a visibly
        # worse portrait with no indication anything went wrong. The caller
        # must see a warning even though the request itself still succeeds.
        from app.media.base import MediaResult
        brand, character, variant = brand_and_character
        session = db()
        row = session.query(Character).filter_by(id=uuid.UUID(character["id"])).first()
        row.base_image_url = "https://supabase/char-portrait.png"
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.culture_tag = "chinese"
        session.commit()
        session.close()

        mocker.patch(
            "app.routers.culturetoons._expand_variant_visual_description",
            return_value=("Chinese version of the character", True),
        )
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/variant-gen.png")

        result = culturetoons.generate_variant_image(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"], "description": "Chinese version of the character",
        })

        assert result["image_url"] == "https://supabase/variant-gen.png"
        assert "generation_warning" in result
        assert "expansion" in result["generation_warning"].lower()

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

    def test_culture_tag_drops_reference_image_for_correct_ethnicity(self, db, user_id, brand_and_character, mocker):
        # Confirmed live (real Qwen-Image calls, side by side): a variant
        # with no photo of its own but an explicit culture_tag signaling a
        # different ethnicity than the base character reliably renders with
        # the REFERENCE character's ethnicity, not the requested one, when
        # grounded on the base character's photo — no prompt wording fixed
        # it. Dropping the reference image entirely (text-only generation)
        # is what actually produces the requested ethnicity.
        from app.media.base import MediaResult
        brand, character, variant = brand_and_character
        session = db()
        row = session.query(Character).filter_by(id=uuid.UUID(character["id"])).first()
        row.base_image_url = "https://supabase/char-portrait.png"
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.culture_tag = "chinese"
        session.commit()
        session.close()

        mock_expand = mocker.patch(
            "app.routers.culturetoons._expand_variant_visual_description",
            return_value=("A Chinese man in his 30s with black hair, oval face, modern attire.", False),
        )
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/variant-gen.png")

        culturetoons.generate_variant_image(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"], "description": "Chinese version of the character",
        })

        mock_expand.assert_called_once()
        _, kwargs = mock_generate.call_args
        assert kwargs["reference_image_url"] is None
        sent_prompt = mock_generate.call_args[0][0]
        assert "recasting" not in sent_prompt.lower()
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
    def test_delete_variant_archives_not_deletes(self, db, user_id, brand_and_character):
        # brand_and_character's Character auto-creates its own default
        # variant on top of the explicit "Indian Mom" one the fixture also
        # creates, so the active list still has one entry (the default
        # variant) after archiving "Indian Mom" — assert on that specific
        # variant's is_active flag, not on the whole list being empty.
        brand, _character, variant = brand_and_character
        culturetoons.delete_variant(variant["id"], user_id, brand["id"])

        active_ids = {v["id"] for v in culturetoons.list_variants(user_id, brand["id"])}
        assert variant["id"] not in active_ids

        archived = culturetoons.list_variants(user_id, brand["id"], active_only=False)
        archived_variant = next(v for v in archived if v["id"] == variant["id"])
        assert archived_variant["is_active"] is False

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

    def test_generate_expression_image_requires_variant_portrait(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_expression_image(
                variant["id"], "Angry", {"user_id": user_id, "brand_id": brand["id"]},
            )
        assert exc_info.value.status_code == 400

    def test_generate_expression_image_rejects_invalid_name(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_expression_image(
                variant["id"], "Bored", {"user_id": user_id, "brand_id": brand["id"]},
            )
        assert exc_info.value.status_code == 400

    def test_generate_expression_image_grounds_on_variant_portrait(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, _character, variant = brand_and_character
        session = db()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.image_url = "https://supabase/variant-portrait.png"
        session.commit()
        session.close()

        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/expr-angry.png")

        result = culturetoons.generate_expression_image(
            variant["id"], "Angry", {"user_id": user_id, "brand_id": brand["id"]},
        )

        assert result["name"] == "Angry"
        assert result["image_url"] == "https://supabase/expr-angry.png"
        _, kwargs = mock_generate.call_args
        assert kwargs["reference_image_url"] == "https://supabase/variant-portrait.png"
        sent_prompt = mock_generate.call_args[0][0]
        assert "same clothing" in sent_prompt.lower()
        assert "angry" in sent_prompt.lower()

        # Regenerating overwrites rather than duplicating, same as upload.
        culturetoons.generate_expression_image(
            variant["id"], "Angry", {"user_id": user_id, "brand_id": brand["id"]},
        )
        expressions = culturetoons.list_expressions(variant["id"], user_id, brand["id"])
        assert len(expressions) == 1

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


class TestGenerateBackground:
    """The standalone, no-script generator behind the Backgrounds tab's
    reusable pool — previously that tab was upload-only with zero AI
    assist, even though generate_script_background's exact same prompt/
    generate/save logic (_generate_background_asset) already existed."""

    def test_requires_description(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_background({"user_id": user_id, "brand_id": brand["id"]})
        assert exc_info.value.status_code == 400

    def test_generates_without_a_script(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, _character, _variant = brand_and_character
        mock_generate = mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png"),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/bg-gen.png")

        result = culturetoons.generate_background({
            "user_id": user_id, "brand_id": brand["id"],
            "description": "An Indian wedding mandap decorated with marigold garlands and string lights",
            "name": "Indian Wedding", "art_style": "cinematic_cultural",
        })

        assert result["image_url"] == "https://supabase/bg-gen.png"
        assert result["name"] == "Indian Wedding"
        sent_prompt = mock_generate.call_args[0][0]
        assert "no people, no characters" in sent_prompt.lower()
        assert "marigold garlands" in sent_prompt

        listed = culturetoons.list_backgrounds(user_id, brand["id"])
        assert len(listed) == 1

    def test_unknown_art_style_400s(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_background({
                "user_id": user_id, "brand_id": brand["id"],
                "description": "A scene", "art_style": "not_a_real_style",
            })
        assert exc_info.value.status_code == 400


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


class TestPublishToon:
    def _make_ready_toon(self, user_id, brand_id, variant_id):
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand_id, "character_variant_id": variant_id})
        toon = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand_id,
            "character_variant_id": variant_id, "script_id": script["id"],
        })
        return culturetoons.update_toon(toon["id"], {
            "user_id": user_id, "brand_id": brand_id,
            "final_video_url": "https://example.com/v.mp4", "status": "ready",
        })

    def _connect_account(self, db, user_id, brand_id, platform="tiktok"):
        from app.social.crypto import encrypt
        session = db()
        account = ConnectedAccount(
            user_id=uuid.UUID(user_id), character_brand_id=uuid.UUID(brand_id),
            platform=platform, access_token=encrypt("plain-token"), status="active",
        )
        session.add(account)
        session.commit()
        session.close()

    def test_publish_requires_final_video(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        toon = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_id": variant["id"], "script_id": script["id"],
        })
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.publish_toon(
                toon["id"], {"user_id": user_id, "brand_id": brand["id"], "platform": "tiktok"},
                background_tasks=BackgroundTasks(),
            )
        assert exc_info.value.status_code == 400

    def test_publish_requires_connected_account(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        toon = self._make_ready_toon(user_id, brand["id"], variant["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.publish_toon(
                toon["id"], {"user_id": user_id, "brand_id": brand["id"], "platform": "tiktok"},
                background_tasks=BackgroundTasks(),
            )
        assert exc_info.value.status_code == 400
        assert "connect" in exc_info.value.detail.lower()

    def test_publish_creates_pending_post_and_queues_background_task(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        toon = self._make_ready_toon(user_id, brand["id"], variant["id"])
        self._connect_account(db, user_id, brand["id"], platform="tiktok")

        bg = BackgroundTasks()
        result = culturetoons.publish_toon(
            toon["id"], {"user_id": user_id, "brand_id": brand["id"], "platform": "tiktok"},
            background_tasks=bg,
        )
        assert result["status"] == "pending"
        assert result["toon_id"] == toon["id"]
        assert result["platform"] == "tiktok"
        assert len(bg.tasks) == 1

        posts = culturetoons.list_toon_posts(toon["id"], user_id, brand["id"])
        assert len(posts) == 1
        assert posts[0]["id"] == result["id"]

    def test_refresh_requires_ownership(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        toon = self._make_ready_toon(user_id, brand["id"], variant["id"])
        self._connect_account(db, user_id, brand["id"], platform="tiktok")
        post = culturetoons.publish_toon(
            toon["id"], {"user_id": user_id, "brand_id": brand["id"], "platform": "tiktok"},
            background_tasks=BackgroundTasks(),
        )

        other_user = str(uuid.uuid4())
        other_brand = culturetoons.create_brand({"user_id": other_user})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.refresh_toon_post(
                post["id"], {"user_id": other_user, "brand_id": other_brand["id"]},
                background_tasks=BackgroundTasks(),
            )
        assert exc_info.value.status_code == 404

    def test_refresh_queues_background_task(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        toon = self._make_ready_toon(user_id, brand["id"], variant["id"])
        self._connect_account(db, user_id, brand["id"], platform="tiktok")
        post = culturetoons.publish_toon(
            toon["id"], {"user_id": user_id, "brand_id": brand["id"], "platform": "tiktok"},
            background_tasks=BackgroundTasks(),
        )

        bg = BackgroundTasks()
        result = culturetoons.refresh_toon_post(post["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=bg)
        assert result["status"] == "refresh_started"
        assert len(bg.tasks) == 1


class TestEpisodes:
    def _make_toon_with_video(self, user_id, brand_id, variant_id, raw_video_url="https://example.com/raw.mp4"):
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand_id, "character_variant_id": variant_id})
        toon = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand_id,
            "character_variant_id": variant_id, "script_id": script["id"],
        })
        return culturetoons.update_toon(toon["id"], {"user_id": user_id, "brand_id": brand_id, "raw_video_url": raw_video_url})

    def test_create_and_list_episode(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"], "title": "Kumar's Big Day"})
        assert episode["status"] == "draft"
        assert episode["parts"] == []

        listed = culturetoons.list_episodes(user_id, brand["id"])
        assert len(listed) == 1
        assert listed[0]["id"] == episode["id"]

    def test_attach_part_assigns_order_and_appears_in_episode(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon1 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        toon2 = self._make_toon_with_video(user_id, brand["id"], variant["id"])

        result = culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon1["id"]})
        assert result["parts"][0]["order_index"] == 0
        result = culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon2["id"]})
        assert [p["order_index"] for p in result["parts"]] == [0, 1]
        assert [p["toon_id"] for p in result["parts"]] == [toon1["id"], toon2["id"]]

    def test_attach_part_already_in_episode_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode1 = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        episode2 = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        culturetoons.attach_episode_part(episode1["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon["id"]})

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.attach_episode_part(episode2["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon["id"]})
        assert exc_info.value.status_code == 400

    def test_detach_part_frees_toon_without_deleting_it(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon["id"]})

        result = culturetoons.detach_episode_part(episode["id"], toon["id"], user_id, brand["id"])
        assert result["parts"] == []
        still_exists = culturetoons.get_toon(toon["id"], user_id, brand["id"])
        assert still_exists["episode_id"] is None

    def test_reorder_parts(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon1 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        toon2 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon1["id"]})
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon2["id"]})

        result = culturetoons.reorder_episode_parts(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "toon_ids": [toon2["id"], toon1["id"]],
        })
        assert [p["toon_id"] for p in result["parts"]] == [toon2["id"], toon1["id"]]
        assert [p["order_index"] for p in result["parts"]] == [0, 1]

    def test_reorder_rejects_mismatched_toon_ids(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon1 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon1["id"]})

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.reorder_episode_parts(episode["id"], {
                "user_id": user_id, "brand_id": brand["id"], "toon_ids": [str(uuid.uuid4())],
            })
        assert exc_info.value.status_code == 400

    def test_stitch_requires_min_two_parts_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon1 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon1["id"]})

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.stitch_episode_endpoint(
                episode["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=_FakeBackgroundTasks(),
            )
        assert exc_info.value.status_code == 400

    def test_stitch_requires_all_parts_have_raw_video_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon1 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        script2 = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        toon2 = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_id": variant["id"], "script_id": script2["id"],
        })  # no raw_video_url
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon1["id"]})
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon2["id"]})

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.stitch_episode_endpoint(
                episode["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=_FakeBackgroundTasks(),
            )
        assert exc_info.value.status_code == 400
        assert "1" in exc_info.value.detail  # names the unready part's order_index

    def test_stitch_queues_background_task_and_sets_stitching_status(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon1 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        toon2 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon1["id"]})
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon2["id"]})

        bg = BackgroundTasks()
        result = culturetoons.stitch_episode_endpoint(episode["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=bg)
        assert result["status"] == "stitching_started"
        assert len(bg.tasks) == 1

        updated = culturetoons.get_episode(episode["id"], user_id, brand["id"])
        assert updated["status"] == "stitching"

    def test_generate_clips_requires_stitched_video_400s(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_episode_clips_endpoint(
                episode["id"], {"user_id": user_id, "brand_id": brand["id"]}, background_tasks=_FakeBackgroundTasks(),
            )
        assert exc_info.value.status_code == 400

    def test_suggest_next_requires_idea_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_next_episode_part(episode["id"], {
                "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            })
        assert exc_info.value.status_code == 400

    def test_suggest_next_requires_cast_400s(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_next_episode_part(episode["id"], {
                "user_id": user_id, "brand_id": brand["id"], "idea": "something happens next",
            })
        assert exc_info.value.status_code == 400

    def test_suggest_next_requires_existing_part_with_script_400s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.suggest_next_episode_part(episode["id"], {
                "user_id": user_id, "brand_id": brand["id"], "idea": "something happens next",
                "character_variant_id": variant["id"],
            })
        assert exc_info.value.status_code == 400
        assert "no parts" in exc_info.value.detail.lower()

    def test_suggest_next_creates_script_and_attaches_as_next_part(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        toon1 = self._make_toon_with_video(user_id, brand["id"], variant["id"])
        session = db()
        script1 = session.query(ToonScript).filter_by(id=uuid.UUID(toon1["script_id"])).first()
        script1.shots = [{"shot_number": 1, "duration_seconds": 4, "action": "waves hello", "expression": "Happy", "dialogue": "Hi there!"}]
        session.commit()
        session.close()
        culturetoons.attach_episode_part(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "toon_id": toon1["id"]})

        fake_shots = [{"shot_number": 1, "duration_seconds": 5, "action": "reacts", "expression": "Shocked", "dialogue": None}]
        mock_generate = mocker.patch(
            "app.services.culturetoon_script.generate_toon_script_continuing_episode",
            return_value={"hook_line": "Part 2 begins", "tone": "funny", "shots": fake_shots, "total_duration_seconds": 5},
        )

        result = culturetoons.suggest_next_episode_part(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "idea": "something surprising happens",
            "character_variant_id": variant["id"],
        })

        assert len(result["parts"]) == 2
        assert result["parts"][0]["toon_id"] == toon1["id"]
        assert result["parts"][1]["order_index"] == 1
        assert result["parts"][1]["title"] == "Part 2 begins"

        sent_summary = mock_generate.call_args[0][0]
        assert "waves hello" in sent_summary
        assert "Hi there!" in sent_summary
        sent_idea = mock_generate.call_args[0][1]
        assert sent_idea == "something surprising happens"


class TestPersonality:
    def test_valid_personality_saved(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        personality = {
            "traits": {"confidence": 0.9, "humor": 0.8},
            "behavioral_rules": ["tries to negotiate when prices seem high"],
            "speech_rules": ["speaks confidently"],
        }
        result = culturetoons.update_character(character["id"], {
            "user_id": user_id, "brand_id": brand["id"], "personality": personality,
        })
        assert result["personality"] == personality

    def test_personality_must_be_object(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_character(character["id"], {
                "user_id": user_id, "brand_id": brand["id"], "personality": "not an object",
            })
        assert exc_info.value.status_code == 400

    def test_personality_rejects_unknown_keys(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_character(character["id"], {
                "user_id": user_id, "brand_id": brand["id"],
                "personality": {"traits": {}, "made_up_field": True},
            })
        assert exc_info.value.status_code == 400

    def test_trait_value_must_be_0_to_1(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_character(character["id"], {
                "user_id": user_id, "brand_id": brand["id"],
                "personality": {"traits": {"confidence": 1.5}},
            })
        assert exc_info.value.status_code == 400

    def test_behavioral_rules_must_be_list_of_strings(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_character(character["id"], {
                "user_id": user_id, "brand_id": brand["id"],
                "personality": {"behavioral_rules": "not a list"},
            })
        assert exc_info.value.status_code == 400


class TestCharacterRelationships:
    def _second_character(self, user_id, brand_id, name="Hans"):
        return culturetoons.create_character({"user_id": user_id, "brand_id": brand_id, "name": name})

    def test_create_requires_two_distinct_characters(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": character["id"], "character_b_id": character["id"],
            })
        assert exc_info.value.status_code == 400

    def test_create_and_list(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])

        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": character["id"], "character_b_id": hans["id"],
            "relationship_type": "friendly_rivalry",
            "description": "Kumar finds Hans excessively rule-oriented.",
            "conflict_level": 4, "trust_level": 7,
            "behavioral_rules": ["Kumar attempts to persuade Hans.", "Hans responds literally."],
        })
        assert created["relationship_type"] == "friendly_rivalry"
        assert created["conflict_level"] == 4

        listed = culturetoons.list_relationships(user_id, brand["id"])
        assert len(listed) == 1
        assert listed[0]["id"] == created["id"]

        # Filtering by either character in the pair returns it — the
        # relationship is order-independent.
        by_a = culturetoons.list_relationships(user_id, brand["id"], character_id=character["id"])
        by_b = culturetoons.list_relationships(user_id, brand["id"], character_id=hans["id"])
        assert len(by_a) == 1 and len(by_b) == 1

    def test_level_fields_must_be_0_to_10(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": character["id"], "character_b_id": hans["id"],
                "conflict_level": 11,
            })
        assert exc_info.value.status_code == 400

    def test_update_and_delete_archives(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": character["id"], "character_b_id": hans["id"],
        })

        updated = culturetoons.update_relationship(created["id"], {
            "user_id": user_id, "brand_id": brand["id"], "trust_level": 9,
        })
        assert updated["trust_level"] == 9

        culturetoons.delete_relationship(created["id"], user_id, brand["id"])
        assert culturetoons.list_relationships(user_id, brand["id"]) == []
        archived = culturetoons.list_relationships(user_id, brand["id"], active_only=False)
        assert len(archived) == 1 and archived[0]["is_active"] is False

    def test_resolve_relationships_for_cast(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        third = self._second_character(user_id, brand["id"], name="Pierre")
        culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": character["id"], "character_b_id": hans["id"],
            "relationship_type": "friendly_rivalry",
        })

        session = db()
        # Cast includes Kumar + Hans -> relationship resolves.
        found = culturetoons.resolve_relationships_for_cast(session, brand["id"], [character["id"], hans["id"]])
        assert len(found) == 1
        assert found[0]["relationship_type"] == "friendly_rivalry"

        # Cast includes only Pierre + Hans (no stored relationship) -> empty.
        none_found = culturetoons.resolve_relationships_for_cast(session, brand["id"], [third["id"], hans["id"]])
        assert none_found == []

        # Fewer than 2 distinct characters -> empty, no query needed.
        assert culturetoons.resolve_relationships_for_cast(session, brand["id"], [character["id"]]) == []
        session.close()

    def test_cross_brand_character_404s(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        other_brand = culturetoons.create_brand({"user_id": user_id, "name": "Other Brand"})
        other_character = culturetoons.create_character({"user_id": user_id, "brand_id": other_brand["id"], "name": "Outsider"})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": character["id"], "character_b_id": other_character["id"],
            })
        assert exc_info.value.status_code == 404


class TestBudgetEnforcement:
    def _exhaust_budget(self, db, brand_id, user_id, amount="10.00"):
        from decimal import Decimal
        from app.services.culturetoon_usage import record_usage
        session = db()
        record_usage(session, user_id=user_id, brand_id=brand_id, provider="kling_omni",
                     generation_type="video", cost_usd=Decimal(amount))
        session.commit()
        session.close()

    def test_update_brand_validates_budget_fields(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": "not-a-number"})
        assert exc_info.value.status_code == 400

        updated = culturetoons.update_brand(brand["id"], {
            "user_id": user_id, "daily_budget": 5, "monthly_budget": 100,
        })
        assert updated["daily_budget"] == 5.0
        assert updated["monthly_budget"] == 100.0

    def test_character_image_generation_blocked_when_monthly_budget_exhausted(self, db, user_id, brand_and_character, mocker):
        brand, character, _variant = brand_and_character
        culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": 10})
        self._exhaust_budget(db, brand["id"], user_id, amount="10.00")

        mock_generate = mocker.patch("app.media.image_hybrid.HybridImageProvider.generate")
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_character_image(character["id"], {
                "user_id": user_id, "brand_id": brand["id"], "description": "A tall man",
            })
        assert exc_info.value.status_code == 402
        mock_generate.assert_not_called()  # blocked before spending anything further

    def test_variant_image_generation_blocked_when_monthly_budget_exhausted(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": 10})
        self._exhaust_budget(db, brand["id"], user_id, amount="10.00")

        mock_generate = mocker.patch("app.media.image_hybrid.HybridImageProvider.generate")
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_variant_image(variant["id"], {
                "user_id": user_id, "brand_id": brand["id"], "description": "A relative",
            })
        assert exc_info.value.status_code == 402
        mock_generate.assert_not_called()

    def test_not_blocked_under_budget_and_warning_surfaced_near_limit(self, db, user_id, brand_and_character, mocker):
        from app.media.base import MediaResult
        brand, character, _variant = brand_and_character
        culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": 10})
        self._exhaust_budget(db, brand["id"], user_id, amount="8.50")  # 85% of budget

        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png", cost_usd=0.1),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/char-gen.png")

        result = culturetoons.generate_character_image(character["id"], {
            "user_id": user_id, "brand_id": brand["id"], "description": "A tall man",
        })
        assert "budget_warning" in result
        assert "80%" in result["budget_warning"] or "85%" in result["budget_warning"]

    def test_generate_toon_video_blocked_before_background_task_fires(self, db, user_id, brand_and_character, mocker):
        # generate_toon_video kicks off a BackgroundTasks job rather than
        # calling Kling synchronously — the budget check must happen before
        # background_tasks.add_task(), not inside the task itself, or a
        # blocked brand would still burn a real Kling call in the background
        # before anyone finds out.
        brand, _character, variant = brand_and_character
        session = db()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.element_status = "ready"
        session.commit()
        script = culturetoons.create_script({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
        })
        script_row = session.query(ToonScript).filter_by(id=uuid.UUID(script["id"])).first()
        script_row.shots = [{"shot_number": 1, "duration_seconds": 4, "action": "waves", "expression": "Happy", "dialogue": "Hi"}]
        session.commit()
        session.close()
        toon = culturetoons.create_toon({
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_id": variant["id"], "script_id": script["id"],
        })

        culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": 10})
        self._exhaust_budget(db, brand["id"], user_id, amount="10.00")

        mock_task = mocker.patch("app.services.culturetoon_video.generate_video_for_toon")
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_toon_video(toon["id"], {"user_id": user_id, "brand_id": brand["id"]}, BackgroundTasks())
        assert exc_info.value.status_code == 402
        mock_task.assert_not_called()

    def test_brand_usage_endpoint_reports_spend(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": 100})
        self._exhaust_budget(db, brand["id"], user_id, amount="25.00")

        usage = culturetoons.get_brand_usage(brand["id"], user_id)
        assert usage["monthly_budget"] == 100.0
        assert usage["monthly_spend"] == 25.0
        assert any(row["generation_type"] == "video" for row in usage["this_month_by_type"])
