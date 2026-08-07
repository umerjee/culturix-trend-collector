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
from app.models.character_relationship_event import CharacterRelationshipEvent
from app.models.character_relationship_direction import CharacterRelationshipDirection
from app.models.character_relationship_behavior_rule import CharacterRelationshipBehaviorRule
from app.models.generation_usage import GenerationUsage
from app.models.character_memory import CharacterMemory
from app.models.culture import Culture
from app.models.toon_scene import ToonScene
from app.models.toon_shot import ToonShot
from app.routers import culturetoons


class _FakeUploadFile:
    def __init__(self, data: bytes, content_type: str):
        self._data = data
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_real_memory_retrieval(mocker):
    # retrieve_relevant_memories talks to real Qdrant/Voyage when
    # QDRANT_URL/VOYAGE_API_KEY are set in the environment (they are, via
    # .env, transitively loaded by app.embeddings) — every suggest_script*
    # test would otherwise make a real network call (and, once the
    # "culturetoon_memories" collection exists in production, a real billed
    # Voyage embedding call) on every test run. Autouse so this is opt-out,
    # not opt-in — a new test that forgets to mock it would otherwise
    # silently start hitting the network. Tests that specifically want to
    # exercise memory retrieval override this mock explicitly.
    return mocker.patch("app.services.culturetoon_memory.retrieve_relevant_memories", return_value=[])


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        Expression.__table__, ToonBackground.__table__, ToonScript.__table__,
        Toon.__table__, ToonPost.__table__, ToonEpisode.__table__, ConnectedAccount.__table__,
        Persona.__table__, Cluster.__table__,
        CharacterRelationship.__table__, GenerationUsage.__table__, CharacterMemory.__table__,
        Culture.__table__, ToonScene.__table__, CharacterRelationshipEvent.__table__,
        CharacterRelationshipDirection.__table__, CharacterRelationshipBehaviorRule.__table__,
        ToonShot.__table__,
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

    def test_create_with_trend_interests(self, db, user_id):
        created = culturetoons.create_brand({
            "user_id": user_id, "name": "Funny Clips", "trend_interests": "family comedy, cultural misunderstandings",
        })
        assert created["trend_interests"] == "family comedy, cultural misunderstandings"

    def test_update_trend_interests_clears_cached_embedding(self, db, user_id):
        from app.models.character_brand import CharacterBrand
        brand = culturetoons.create_brand({"user_id": user_id, "trend_interests": "original interests"})
        session = db()
        row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
        row.trend_interests_embedding = [0.1, 0.2, 0.3]  # pretend it was already computed once
        session.commit()
        session.close()

        updated = culturetoons.update_brand(brand["id"], {
            "user_id": user_id, "trend_interests": "different interests now",
        })
        assert updated["trend_interests"] == "different interests now"

        session = db()
        row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
        assert row.trend_interests_embedding is None  # stale cache invalidated
        session.close()

    def test_update_trend_interests_same_value_keeps_cache(self, db, user_id):
        from app.models.character_brand import CharacterBrand
        brand = culturetoons.create_brand({"user_id": user_id, "trend_interests": "family comedy"})
        session = db()
        row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
        row.trend_interests_embedding = [0.1, 0.2, 0.3]
        session.commit()
        session.close()

        culturetoons.update_brand(brand["id"], {"user_id": user_id, "trend_interests": "family comedy"})

        session = db()
        row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
        assert row.trend_interests_embedding == [0.1, 0.2, 0.3]  # unchanged, no invalidation needed
        session.close()


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


class TestCultureLibrary:
    def test_create_and_list(self, db, user_id):
        created = culturetoons.create_culture({
            "user_id": user_id, "name": "Testonian", "country": "Testonia",
            "humor_sensitivity": "self-deprecating humor lands well",
            "stereotypes_to_avoid": ["lazy caricature"],
        })
        assert created["name"] == "Testonian"

        listed = culturetoons.list_cultures()
        assert any(c["name"] == "Testonian" for c in listed)

    def test_duplicate_name_conflicts(self, db, user_id):
        culturetoons.create_culture({"user_id": user_id, "name": "Testonian"})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_culture({"user_id": user_id, "name": "Testonian"})
        assert exc_info.value.status_code == 409

    def test_requires_name(self, db, user_id):
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_culture({"user_id": user_id})
        assert exc_info.value.status_code == 400

    def test_variant_links_to_culture(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        culture = culturetoons.create_culture({"user_id": user_id, "name": "Testonian"})

        updated = culturetoons.update_variant(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"], "culture_id": culture["id"],
        })
        assert updated["culture_id"] == culture["id"]

    def test_unknown_culture_id_404s(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_variant(variant["id"], {
                "user_id": user_id, "brand_id": brand["id"], "culture_id": str(uuid.uuid4()),
            })
        assert exc_info.value.status_code == 404

    def test_gather_script_context_resolves_linked_culture(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        culture = culturetoons.create_culture({
            "user_id": user_id, "name": "Testonian", "humor_sensitivity": "self-deprecating humor lands well",
        })
        culturetoons.update_variant(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"], "culture_id": culture["id"],
        })

        session = db()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        _personalities, _relationships, _memories, cultures, _performance = culturetoons._gather_script_generation_context(
            session, brand["id"], [variant_row]
        )
        session.close()

        assert len(cultures) == 1
        assert cultures[0]["name"] == "Testonian"


class TestCharacterMemories:
    def test_create_requires_valid_memory_type(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_memory(variant["id"], {
                "user_id": user_id, "brand_id": brand["id"],
                "memory_type": "not_a_real_type", "content": "Something happened.",
            })
        assert exc_info.value.status_code == 400

    def test_create_and_list(self, db, user_id, brand_and_character, mocker):
        mock_index = mocker.patch("app.services.culturetoon_memory.index_memory")
        brand, _character, variant = brand_and_character

        created = culturetoons.create_memory(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "memory_type": "running_gag", "content": "Once tried to negotiate a Swiss train ticket.",
            "importance": 7,
        })
        assert created["memory_type"] == "running_gag"
        assert created["importance"] == 7
        mock_index.assert_called_once()

        listed = culturetoons.list_memories(variant["id"], user_id, brand["id"])
        assert len(listed) == 1
        assert listed[0]["id"] == created["id"]

    def test_importance_must_be_0_to_10(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_memory(variant["id"], {
                "user_id": user_id, "brand_id": brand["id"],
                "memory_type": "preference", "content": "Loves spicy food.", "importance": 99,
            })
        assert exc_info.value.status_code == 400

    def test_delete_removes_from_db_and_index(self, db, user_id, brand_and_character, mocker):
        mocker.patch("app.services.culturetoon_memory.index_memory")
        mock_delete_index = mocker.patch("app.services.culturetoon_memory.delete_memory_index")
        brand, _character, variant = brand_and_character

        created = culturetoons.create_memory(variant["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "memory_type": "preference", "content": "Loves spicy food.",
        })
        culturetoons.delete_memory(created["id"], user_id, brand["id"])

        assert culturetoons.list_memories(variant["id"], user_id, brand["id"]) == []
        mock_delete_index.assert_called_once_with(created["id"])

    def test_cross_brand_variant_404s(self, db, user_id, brand_and_character):
        _brand, _character, variant = brand_and_character
        other_brand = culturetoons.create_brand({"user_id": user_id, "name": "Other Brand"})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_memory(variant["id"], {
                "user_id": user_id, "brand_id": other_brand["id"],
                "memory_type": "preference", "content": "Loves spicy food.",
            })
        assert exc_info.value.status_code == 404


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

    def test_country_and_visual_style_set_on_create(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        bg = culturetoons.create_background({
            "user_id": user_id, "brand_id": brand["id"], "name": "Mandap",
            "country": "India", "visual_style": "cinematic_cultural",
        })
        assert bg["country"] == "India"
        assert bg["visual_style"] == "cinematic_cultural"
        assert bg["reference_image_urls"] == []

    def test_invalid_visual_style_rejected_on_create(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_background({
                "user_id": user_id, "brand_id": brand["id"], "name": "Mandap",
                "visual_style": "not_a_real_style",
            })
        assert exc_info.value.status_code == 400

    def test_update_country_and_visual_style(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        bg = culturetoons.create_background({"user_id": user_id, "brand_id": brand["id"], "name": "Mandap"})
        updated = culturetoons.update_background(bg["id"], {
            "user_id": user_id, "brand_id": brand["id"], "country": "Switzerland", "visual_style": "anime",
        })
        assert updated["country"] == "Switzerland"
        assert updated["visual_style"] == "anime"

    def test_invalid_visual_style_rejected_on_update(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        bg = culturetoons.create_background({"user_id": user_id, "brand_id": brand["id"], "name": "Mandap"})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_background(bg["id"], {
                "user_id": user_id, "brand_id": brand["id"], "visual_style": "not_a_real_style",
            })
        assert exc_info.value.status_code == 400

    def test_add_and_remove_reference_images(self, db, user_id, mocker):
        brand = culturetoons.create_brand({"user_id": user_id})
        bg = culturetoons.create_background({"user_id": user_id, "brand_id": brand["id"], "name": "House"})

        mocker.patch("app.media.storage.upload", side_effect=[
            "https://supabase/house-angle-1.png", "https://supabase/house-angle-2.png",
        ])
        result = _run(culturetoons.upload_background_reference_image(
            bg["id"], user_id=user_id, brand_id=brand["id"], file=_FakeUploadFile(b"fake-png-1", "image/png"),
        ))
        assert result["reference_image_urls"] == ["https://supabase/house-angle-1.png"]

        result = _run(culturetoons.upload_background_reference_image(
            bg["id"], user_id=user_id, brand_id=brand["id"], file=_FakeUploadFile(b"fake-png-2", "image/png"),
        ))
        assert result["reference_image_urls"] == [
            "https://supabase/house-angle-1.png", "https://supabase/house-angle-2.png",
        ]
        # Primary image_url is untouched by adding reference angles.
        assert result["image_url"] is None

        removed = culturetoons.delete_background_reference_image(
            bg["id"], user_id, brand["id"], "https://supabase/house-angle-1.png",
        )
        assert removed["reference_image_urls"] == ["https://supabase/house-angle-2.png"]

    def test_generate_background_stores_visual_style_and_country(self, db, user_id, mocker):
        from app.media.base import MediaResult
        brand = culturetoons.create_brand({"user_id": user_id})
        mocker.patch(
            "app.media.image_hybrid.HybridImageProvider.generate",
            return_value=MediaResult(asset_bytes=b"fake-png", content_type="image/png", cost_usd=0.1),
        )
        mocker.patch("app.media.storage.upload", return_value="https://supabase/generated.png")

        result = culturetoons.generate_background({
            "user_id": user_id, "brand_id": brand["id"],
            "description": "A Swiss chalet interior, empty of people",
            "art_style": "flat_vector", "country": "Switzerland",
        })
        assert result["visual_style"] == "flat_vector"
        assert result["country"] == "Switzerland"


class TestTrendSources:
    def _persona(self, db, name, description, status="active"):
        session = db()
        p = Persona(name=name, description=description, status=status)
        session.add(p)
        session.commit()
        session.refresh(p)
        session.close()
        return p

    def _cluster(self, db, theme, summary):
        session = db()
        c = Cluster(label=1, theme=theme, summary=summary)
        session.add(c)
        session.commit()
        session.refresh(c)
        session.close()
        return c

    def test_no_interests_returns_unfiltered_recent_feed(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        self._persona(db, "Solar Eclipse Watchers", "People tracking the August 2026 eclipse")
        self._cluster(db, "Football players", "Recent football player news")

        result = culturetoons.get_trend_sources(user_id, brand["id"])
        assert result["personalized"] is False
        assert len(result["personas"]) == 1
        assert len(result["clusters"]) == 1

    def test_inactive_personas_excluded(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id})
        self._persona(db, "Dormant One", "Not active anymore", status="dormant")

        result = culturetoons.get_trend_sources(user_id, brand["id"])
        assert result["personas"] == []

    def test_personalized_ranking_when_interests_set(self, db, user_id, mocker):
        brand = culturetoons.create_brand({"user_id": user_id, "trend_interests": "family comedy"})
        family = self._persona(db, "Chaotic Family Dinners", "Relatable family dinner chaos")
        eclipse = self._persona(db, "Solar Eclipse Watchers", "People tracking an astronomical event")

        def fake_embed_batch(texts):
            # Family-comedy text embeds close to the brand's interests
            # vector; the eclipse text embeds far from it.
            return [[1.0, 0.0] if "Family" in t else [0.0, 1.0] for t in texts]

        mocker.patch("app.embeddings.embed_text", return_value=[1.0, 0.0])
        mocker.patch("app.embeddings.embed_batch", side_effect=fake_embed_batch)

        result = culturetoons.get_trend_sources(user_id, brand["id"])
        assert result["personalized"] is True
        assert result["personas"][0]["id"] == family.id
        assert result["personas"][-1]["id"] == eclipse.id

    def test_embedding_failure_falls_back_to_unfiltered(self, db, user_id, mocker):
        brand = culturetoons.create_brand({"user_id": user_id, "trend_interests": "family comedy"})
        self._persona(db, "Some Trend", "A description")
        mocker.patch("app.embeddings.embed_text", side_effect=RuntimeError("Voyage is down"))

        result = culturetoons.get_trend_sources(user_id, brand["id"])
        assert result["personalized"] is False
        assert len(result["personas"]) == 1  # still returned, just unranked


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

    def test_passes_personality_and_relationships_to_generator(self, db, user_id, brand_and_character, mocker):
        # Locks in the Phase 3 wiring: _gather_script_generation_context
        # resolves each cast character's personality and any relationship
        # between them, and suggest_script_from_idea forwards both to the
        # generator so identity stays deterministic instead of being
        # re-improvised per script.
        brand, character, variant = brand_and_character
        culturetoons.update_character(character["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "personality": {"traits": {"confidence": 0.9}, "behavioral_rules": ["negotiates hard"]},
        })
        hans = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Hans"})
        hans_variant = culturetoons.create_variant({
            "user_id": user_id, "brand_id": brand["id"], "character_id": hans["id"], "name": "Hans",
        })
        culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": character["id"], "character_b_id": hans["id"],
            "relationship_type": "friendly_rivalry",
        })

        fake_shots = [{"shot_number": 1, "duration_seconds": 4, "action": "argues", "expression": "Annoyed", "dialogue": "No!"}]
        mock_generate = mocker.patch(
            "app.services.culturetoon_script.generate_toon_script_from_idea",
            return_value={"hook_line": "H", "tone": "funny", "shots": fake_shots, "total_duration_seconds": 4},
        )
        culturetoons.suggest_script_from_idea({
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_ids": [variant["id"], hans_variant["id"]],
            "idea": "They argue about recycling", "tone": "funny",
        })

        kwargs = mock_generate.call_args.kwargs
        assert kwargs["character_personalities"][character["id"]]["behavioral_rules"] == ["negotiates hard"]
        assert kwargs["relationships"][0]["relationship_type"] == "friendly_rivalry"

    def test_passes_retrieved_memories_to_generator(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        mock_retrieve = mocker.patch(
            "app.services.culturetoon_memory.retrieve_relevant_memories",
            return_value=["Once tried to negotiate a Swiss train ticket."],
        )
        mock_generate = mocker.patch(
            "app.services.culturetoon_script.generate_toon_script_from_idea",
            return_value={"hook_line": "H", "tone": "funny", "shots": [], "total_duration_seconds": 4},
        )
        culturetoons.suggest_script_from_idea({
            "user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"],
            "idea": "Tries to negotiate a train ticket", "tone": "funny",
        })

        mock_retrieve.assert_called_once()
        assert mock_retrieve.call_args.args[1] == "Tries to negotiate a train ticket"
        assert mock_generate.call_args.kwargs["memories"] == ["Once tried to negotiate a Swiss train ticket."]

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


class TestScenes:
    def test_create_scene_auto_numbers(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})

        scene1 = culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "character_variant_ids": [variant["id"]], "action": "arrives confused", "dialogue": "Huh?",
        })
        scene2 = culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        assert scene1["scene_number"] == 1
        assert scene1["status"] == "idea"
        assert scene1["character_variant_ids"] == [variant["id"]]
        assert scene2["scene_number"] == 2

    def test_create_scene_rejects_invalid_duration(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_scene(episode["id"], {
                "user_id": user_id, "brand_id": brand["id"], "duration_seconds": 30,
            })
        assert exc_info.value.status_code == 400

    def test_create_scene_rejects_foreign_variant(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_scene(episode["id"], {
                "user_id": user_id, "brand_id": brand["id"],
                "character_variant_ids": [str(uuid.uuid4())],
            })
        assert exc_info.value.status_code == 404

    def test_create_scenes_from_script_converts_shots(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        session = db()
        script_row = session.query(ToonScript).filter_by(id=uuid.UUID(script["id"])).first()
        script_row.shots = [
            {"shot_number": 1, "duration_seconds": 4, "action": "waves hello", "expression": "Happy", "dialogue": "Hi!"},
            {"shot_number": 2, "duration_seconds": 5, "action": "reacts", "expression": "Shocked", "dialogue": None},
        ]
        session.commit()
        session.close()

        scenes = culturetoons.create_scenes_from_script(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "script_id": script["id"],
        })

        assert len(scenes) == 2
        assert [s["scene_number"] for s in scenes] == [1, 2]
        assert scenes[0]["action"] == "waves hello"
        assert scenes[0]["dialogue"] == "Hi!"
        assert scenes[1]["expression"] == "Shocked"

    def test_create_scenes_from_script_appends_after_existing_scenes(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"]})
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        session = db()
        script_row = session.query(ToonScript).filter_by(id=uuid.UUID(script["id"])).first()
        script_row.shots = [{"shot_number": 1, "duration_seconds": 4, "action": "enters", "expression": "Happy", "dialogue": None}]
        session.commit()
        session.close()

        scenes = culturetoons.create_scenes_from_script(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "script_id": script["id"],
        })
        assert scenes[0]["scene_number"] == 2

    def test_create_scenes_from_script_requires_shots(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        script = culturetoons.create_script({"user_id": user_id, "brand_id": brand["id"], "character_variant_id": variant["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_scenes_from_script(episode["id"], {
                "user_id": user_id, "brand_id": brand["id"], "script_id": script["id"],
            })
        assert exc_info.value.status_code == 400

    def test_list_scenes_ordered_by_scene_number(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "scene_number": 2})
        culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"], "scene_number": 1})

        listed = culturetoons.list_scenes(episode["id"], user_id, brand["id"])
        assert [s["scene_number"] for s in listed] == [1, 2]

    def test_update_scene_fields(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"]})

        updated = culturetoons.update_scene(scene["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "action": "storms off", "dialogue": "Unbelievable!", "duration_seconds": 6,
        })
        assert updated["action"] == "storms off"
        assert updated["dialogue"] == "Unbelievable!"
        assert updated["duration_seconds"] == 6

    def test_update_scene_rejects_invalid_duration(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_scene(scene["id"], {"user_id": user_id, "brand_id": brand["id"], "duration_seconds": 0})
        assert exc_info.value.status_code == 400

    def test_update_scene_wrong_brand_404s(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"]})
        other_brand = culturetoons.create_brand({"user_id": user_id, "name": "Other Brand"})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_scene(scene["id"], {
                "user_id": user_id, "brand_id": other_brand["id"], "action": "hijacked",
            })
        assert exc_info.value.status_code == 404

    def test_delete_scene_hard_deletes(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"]})

        result = culturetoons.delete_scene(scene["id"], user_id, brand["id"])
        assert result["status"] == "deleted"
        assert culturetoons.list_scenes(episode["id"], user_id, brand["id"]) == []

    def test_generate_scene_requires_cast(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"]})

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_scene(scene["id"], {"user_id": user_id, "brand_id": brand["id"]}, _FakeBackgroundTasks())
        assert exc_info.value.status_code == 400

    def test_generate_scene_requires_ready_element(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_scene(scene["id"], {"user_id": user_id, "brand_id": brand["id"]}, _FakeBackgroundTasks())
        assert exc_info.value.status_code == 400
        assert "Kling element" in exc_info.value.detail

    def test_generate_scene_queues_background_task(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        session = db()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.element_status = "ready"
        session.commit()
        session.close()
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        bg = BackgroundTasks()
        result = culturetoons.generate_scene(scene["id"], {"user_id": user_id, "brand_id": brand["id"]}, bg)
        assert result["status"] == "generation_started"
        assert len(bg.tasks) == 1

        updated = culturetoons.list_scenes(episode["id"], user_id, brand["id"])[0]
        assert updated["status"] == "generating"

    def test_generate_scene_blocked_when_budget_exhausted(self, db, user_id, brand_and_character):
        from decimal import Decimal
        from app.services.culturetoon_usage import record_usage
        brand, _character, variant = brand_and_character
        session = db()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.element_status = "ready"
        session.commit()
        record_usage(session, user_id=user_id, brand_id=brand["id"], provider="kling_omni",
                     generation_type="video", cost_usd=Decimal("10.00"))
        session.commit()
        session.close()
        culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": 10})
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        bg = BackgroundTasks()
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_scene(scene["id"], {"user_id": user_id, "brand_id": brand["id"]}, bg)
        assert exc_info.value.status_code == 402
        assert len(bg.tasks) == 0

    def test_assemble_scenes_requires_at_least_one_ready(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.assemble_episode_from_scenes_endpoint(
                episode["id"], {"user_id": user_id, "brand_id": brand["id"]}, _FakeBackgroundTasks(),
            )
        assert exc_info.value.status_code == 400

    def test_assemble_scenes_queues_background_task_and_sets_stitching(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })
        session = db()
        scene_row = session.query(ToonScene).filter_by(id=uuid.UUID(scene["id"])).first()
        scene_row.status = "ready"
        scene_row.video_url = "https://example.com/scene1.mp4"
        session.commit()
        session.close()

        bg = BackgroundTasks()
        result = culturetoons.assemble_episode_from_scenes_endpoint(
            episode["id"], {"user_id": user_id, "brand_id": brand["id"]}, bg,
        )
        assert result["status"] == "assembly_started"
        assert len(bg.tasks) == 1

        updated = culturetoons.get_episode(episode["id"], user_id, brand["id"])
        assert updated["status"] == "stitching"


class TestShots:
    def _scene(self, user_id, brand_id, variant_id):
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand_id})
        return culturetoons.create_scene(episode["id"], {
            "user_id": user_id, "brand_id": brand_id, "character_variant_ids": [variant_id],
        })

    def test_create_shot_auto_numbers(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])

        shot1 = culturetoons.create_shot(scene["id"], {
            "user_id": user_id, "brand_id": brand["id"], "shot_type": "establishing", "action": "wide shot",
        })
        shot2 = culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})

        assert shot1["shot_number"] == 1
        assert shot1["shot_type"] == "establishing"
        assert shot1["generation_status"] == "idea"
        assert shot2["shot_number"] == 2

    def test_create_shot_rejects_invalid_shot_type(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_shot(scene["id"], {
                "user_id": user_id, "brand_id": brand["id"], "shot_type": "not_a_real_type",
            })
        assert exc_info.value.status_code == 400

    def test_create_shot_rejects_invalid_camera_movement(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_shot(scene["id"], {
                "user_id": user_id, "brand_id": brand["id"], "camera_movement": "nonsense",
            })
        assert exc_info.value.status_code == 400

    def test_create_shot_rejects_invalid_comedic_beat(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_shot(scene["id"], {
                "user_id": user_id, "brand_id": brand["id"], "comedic_beat": "nonsense",
            })
        assert exc_info.value.status_code == 400

    def test_create_shot_rejects_out_of_range_duration(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_shot(scene["id"], {
                "user_id": user_id, "brand_id": brand["id"], "duration_seconds": 10,
            })
        assert exc_info.value.status_code == 400

    def test_create_shot_rejects_foreign_variant(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_shot(scene["id"], {
                "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [str(uuid.uuid4())],
            })
        assert exc_info.value.status_code == 404

    def test_plan_scene_shots_creates_persisted_editable_shots(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        fake_shots = [
            {"shot_type": "establishing", "duration_seconds": 2, "character_variant_ids": [],
             "action": "wide shot", "emotion": None, "dialogue": None, "comedic_beat": "setup",
             "camera_framing": "wide", "camera_angle": "eye level", "camera_movement": "static",
             "lens": "24mm", "composition": "centered", "lighting": "natural"},
            {"shot_type": "closeup", "duration_seconds": 2, "character_variant_ids": [variant["id"]],
             "action": "reacts", "emotion": "Shocked", "dialogue": "Whoa!", "comedic_beat": "punchline",
             "camera_framing": "tight", "camera_angle": "low angle", "camera_movement": "push_in",
             "lens": "85mm", "composition": "close", "lighting": "hard key"},
        ]
        mock_plan = mocker.patch(
            "app.services.culturetoon_cinematic_director.plan_shots", return_value=fake_shots,
        )

        result = culturetoons.plan_scene_shots(scene["id"], {
            "user_id": user_id, "brand_id": brand["id"], "tone": "chaotic", "target_duration_seconds": 15,
        })

        assert len(result) == 2
        assert [s["shot_number"] for s in result] == [1, 2]
        assert result[0]["shot_type"] == "establishing"
        assert result[1]["dialogue"] == "Whoa!"
        mock_plan.assert_called_once()

        listed = culturetoons.list_shots(scene["id"], user_id, brand["id"])
        assert len(listed) == 2

    def test_plan_scene_shots_requires_cast(self, db, user_id, brand_and_character):
        brand, _character, _variant = brand_and_character
        episode = culturetoons.create_episode({"user_id": user_id, "brand_id": brand["id"]})
        scene = culturetoons.create_scene(episode["id"], {"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.plan_scene_shots(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})
        assert exc_info.value.status_code == 400

    def test_plan_scene_shots_appends_after_existing(self, db, user_id, brand_and_character, mocker):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})

        mocker.patch(
            "app.services.culturetoon_cinematic_director.plan_shots",
            return_value=[{
                "shot_type": "medium", "duration_seconds": 3, "character_variant_ids": [],
                "action": "a", "emotion": None, "dialogue": None, "comedic_beat": None,
                "camera_framing": None, "camera_angle": None, "camera_movement": None,
                "lens": None, "composition": None, "lighting": None,
            }],
        )
        result = culturetoons.plan_scene_shots(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})
        assert result[0]["shot_number"] == 2

    def test_list_shots_ordered_by_shot_number(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"], "shot_number": 2})
        culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"], "shot_number": 1})

        listed = culturetoons.list_shots(scene["id"], user_id, brand["id"])
        assert [s["shot_number"] for s in listed] == [1, 2]

    def test_update_shot_fields(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})

        updated = culturetoons.update_shot(shot["id"], {
            "user_id": user_id, "brand_id": brand["id"], "shot_type": "closeup", "camera_angle": "low angle",
        })
        assert updated["shot_type"] == "closeup"
        assert updated["camera_angle"] == "low angle"

    def test_update_shot_rejects_invalid_shot_type(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.update_shot(shot["id"], {
                "user_id": user_id, "brand_id": brand["id"], "shot_type": "nonsense",
            })
        assert exc_info.value.status_code == 400

    def test_delete_shot_hard_deletes(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})

        result = culturetoons.delete_shot(shot["id"], user_id, brand["id"])
        assert result["status"] == "deleted"
        assert culturetoons.list_shots(scene["id"], user_id, brand["id"]) == []

    def test_generate_shot_requires_ready_element(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_shot(shot["id"], {"user_id": user_id, "brand_id": brand["id"]}, _FakeBackgroundTasks())
        assert exc_info.value.status_code == 400
        assert "Kling element" in exc_info.value.detail

    def test_generate_shot_with_no_cast_queues_background_task(self, db, user_id, brand_and_character):
        # An environmental/insert shot legitimately has no character cast.
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {
            "user_id": user_id, "brand_id": brand["id"], "shot_type": "establishing",
        })

        bg = BackgroundTasks()
        result = culturetoons.generate_shot(shot["id"], {"user_id": user_id, "brand_id": brand["id"]}, bg)
        assert result["status"] == "generation_started"
        assert len(bg.tasks) == 1

        updated = culturetoons.list_shots(scene["id"], user_id, brand["id"])[0]
        assert updated["generation_status"] == "generating"

    def test_generate_shot_queues_background_task(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        session = db()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.element_status = "ready"
        session.commit()
        session.close()
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        bg = BackgroundTasks()
        result = culturetoons.generate_shot(shot["id"], {"user_id": user_id, "brand_id": brand["id"]}, bg)
        assert result["status"] == "generation_started"
        assert len(bg.tasks) == 1

    def test_generate_shot_blocked_when_budget_exhausted(self, db, user_id, brand_and_character):
        from decimal import Decimal
        from app.services.culturetoon_usage import record_usage
        brand, _character, variant = brand_and_character
        session = db()
        variant_row = session.query(CharacterVariant).filter_by(id=uuid.UUID(variant["id"])).first()
        variant_row.element_status = "ready"
        session.commit()
        record_usage(session, user_id=user_id, brand_id=brand["id"], provider="kling_omni",
                     generation_type="video", cost_usd=Decimal("10.00"))
        session.commit()
        session.close()
        culturetoons.update_brand(brand["id"], {"user_id": user_id, "monthly_budget": 10})
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {
            "user_id": user_id, "brand_id": brand["id"], "character_variant_ids": [variant["id"]],
        })

        bg = BackgroundTasks()
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_shot(shot["id"], {"user_id": user_id, "brand_id": brand["id"]}, bg)
        assert exc_info.value.status_code == 402
        assert len(bg.tasks) == 0

    def test_assemble_shots_requires_at_least_one_ready(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})

        class _FakeBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pytest.fail("should not have been backgrounded")

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.assemble_scene_from_shots_endpoint(
                scene["id"], {"user_id": user_id, "brand_id": brand["id"]}, _FakeBackgroundTasks(),
            )
        assert exc_info.value.status_code == 400

    def test_assemble_shots_queues_background_task_and_sets_generating(self, db, user_id, brand_and_character):
        brand, _character, variant = brand_and_character
        scene = self._scene(user_id, brand["id"], variant["id"])
        shot = culturetoons.create_shot(scene["id"], {"user_id": user_id, "brand_id": brand["id"]})
        session = db()
        shot_row = session.query(ToonShot).filter_by(id=uuid.UUID(shot["id"])).first()
        shot_row.generation_status = "ready"
        shot_row.generated_asset_id = "https://example.com/shot1.mp4"
        session.commit()
        session.close()

        bg = BackgroundTasks()
        result = culturetoons.assemble_scene_from_shots_endpoint(
            scene["id"], {"user_id": user_id, "brand_id": brand["id"]}, bg,
        )
        assert result["status"] == "assembly_started"
        assert len(bg.tasks) == 1


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
            "conflict_level": 4, "trust_level": 7, "affection_level": 8,
            "behavioral_rules": ["Kumar attempts to persuade Hans.", "Hans responds literally."],
        })
        assert created["relationship_type"] == "friendly_rivalry"
        assert created["conflict_level"] == 4
        assert created["affection_level"] == 8

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

    def test_affection_independent_of_trust(self, db, user_id, brand_and_character):
        # Bickering siblings: low trust, high affection — must be settable
        # independently, not derived from one another.
        brand, character, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": character["id"], "character_b_id": hans["id"],
            "trust_level": 2, "affection_level": 9,
        })
        assert created["trust_level"] == 2
        assert created["affection_level"] == 9

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
        assert found[0]["recent_events"] == []

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


class TestRelationshipDirections:
    """Directional relationship refinement — personality toward another
    character is not necessarily symmetrical, see docs/culturix-
    relationship-refinement.md. Kumar<->Hans, friendly rivalry, is the
    spec's own worked example (item 10's manual verification test),
    reused here as the primary fixture."""

    def _second_character(self, user_id, brand_id, name="Hans"):
        return culturetoons.create_character({"user_id": user_id, "brand_id": brand_id, "name": name})

    def test_create_with_directional_dynamics_not_symmetrical(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])

        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "relationship_type": "friendly_rivalry",
            "a_to_b": {
                "affection_level": 7, "trust_level": 8, "conflict_level": 6,
                "perspective_description": "Hans takes rules too seriously.",
                "behavior_rules": ["tries to persuade Hans to bend rules", "calls Hans \"brother\" when asking for something"],
            },
            "b_to_a": {
                "affection_level": 6, "trust_level": 5, "conflict_level": 9,
                "perspective_description": "Kumar creates unnecessary chaos.",
                "behavior_rules": ["responds literally", "refuses to bend rules", "becomes increasingly frustrated with Kumar"],
            },
        })

        assert len(created["directions"]) == 2
        a_to_b = next(d for d in created["directions"] if d["from_character_id"] == kumar["id"])
        b_to_a = next(d for d in created["directions"] if d["from_character_id"] == hans["id"])

        assert a_to_b["to_character_id"] == hans["id"]
        assert a_to_b["affection_level"] == 7 and a_to_b["trust_level"] == 8 and a_to_b["conflict_level"] == 6
        assert a_to_b["perspective_description"] == "Hans takes rules too seriously."
        assert a_to_b["behavior_rules"] == ["tries to persuade Hans to bend rules", "calls Hans \"brother\" when asking for something"]

        assert b_to_a["to_character_id"] == kumar["id"]
        assert b_to_a["affection_level"] == 6 and b_to_a["trust_level"] == 5 and b_to_a["conflict_level"] == 9
        assert b_to_a["perspective_description"] == "Kumar creates unnecessary chaos."
        assert len(b_to_a["behavior_rules"]) == 3

        # The whole point — not just different objects, genuinely different values.
        assert a_to_b["affection_level"] != b_to_a["affection_level"]
        assert a_to_b["conflict_level"] != b_to_a["conflict_level"]

    def test_relationship_stays_a_single_record_with_exactly_two_directions(self, db, user_id, brand_and_character):
        from app.models.character_relationship import CharacterRelationship
        from app.models.character_relationship_direction import CharacterRelationshipDirection
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])

        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "a_to_b": {"affection_level": 7}, "b_to_a": {"affection_level": 6},
        })
        # Reading it again (list, and re-fetching directions) must not create more rows.
        culturetoons.list_relationships(user_id, brand["id"])
        culturetoons.update_relationship(created["id"], {"user_id": user_id, "brand_id": brand["id"], "description": "edited"})

        session = db()
        relationship_rows = session.query(CharacterRelationship).filter_by(
            character_a_id=uuid.UUID(kumar["id"]), character_b_id=uuid.UUID(hans["id"]),
        ).all()
        assert len(relationship_rows) == 1
        direction_rows = session.query(CharacterRelationshipDirection).filter_by(
            relationship_id=uuid.UUID(created["id"]),
        ).all()
        assert len(direction_rows) == 2
        session.close()

    def test_relationship_type_must_be_valid_enum(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": kumar["id"], "character_b_id": hans["id"],
                "relationship_type": "sworn_enemies_of_destiny",
            })
        assert exc_info.value.status_code == 400

    def test_relationship_type_label_defaults_to_canonical(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "relationship_type": "friendly_rivalry",
        })
        assert created["relationship_type_label"] == "Friendly Rivalry"

    def test_custom_relationship_type_requires_label(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": kumar["id"], "character_b_id": hans["id"],
                "relationship_type": "custom",
            })
        assert exc_info.value.status_code == 400

    def test_custom_relationship_type_with_label_persists(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "relationship_type": "custom", "relationship_type_label": "Frenemies",
        })
        assert created["relationship_type"] == "custom"
        assert created["relationship_type_label"] == "Frenemies"

    def test_comedy_chemistry_persists_and_validated(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "comedy_chemistry": 9,
        })
        assert created["comedy_chemistry"] == 9

        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": kumar["id"], "character_b_id": hans["id"],
                "comedy_chemistry": 11,
            })
        assert exc_info.value.status_code == 400

    def test_direction_level_out_of_range_400s(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": kumar["id"], "character_b_id": hans["id"],
                "a_to_b": {"affection_level": 15},
            })
        assert exc_info.value.status_code == 400

    def test_update_direction_replaces_behavior_rules_not_appends(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "a_to_b": {"behavior_rules": ["old rule one", "old rule two"]},
        })

        updated = culturetoons.update_relationship(created["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "a_to_b": {"behavior_rules": ["new rule"]},
        })
        a_to_b = next(d for d in updated["directions"] if d["from_character_id"] == kumar["id"])
        assert a_to_b["behavior_rules"] == ["new rule"]

    def test_update_only_touches_specified_direction(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "a_to_b": {"affection_level": 7}, "b_to_a": {"affection_level": 6},
        })

        updated = culturetoons.update_relationship(created["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "a_to_b": {"affection_level": 10},
        })
        a_to_b = next(d for d in updated["directions"] if d["from_character_id"] == kumar["id"])
        b_to_a = next(d for d in updated["directions"] if d["from_character_id"] == hans["id"])
        assert a_to_b["affection_level"] == 10
        assert b_to_a["affection_level"] == 6  # untouched

    def test_legacy_relationship_directions_seeded_from_symmetric_fields(self, db, user_id, brand_and_character):
        # Migration path — a relationship created the old way (no a_to_b/
        # b_to_a) must not lose its existing data: reading it after this
        # refinement lazily materializes both directions seeded from the
        # old symmetric fields, not left empty.
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "affection_level": 8, "trust_level": 7, "conflict_level": 4,
            "behavioral_rules": ["Kumar attempts to persuade Hans.", "Hans responds literally."],
        })
        for direction in created["directions"]:
            assert direction["affection_level"] == 8
            assert direction["trust_level"] == 7
            assert direction["conflict_level"] == 4
            assert direction["behavior_rules"] == ["Kumar attempts to persuade Hans.", "Hans responds literally."]

    def test_episodes_together_zero_for_new_relationship(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        created = culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
        })
        assert created["episodes_together"] == 0
        listed = culturetoons.list_relationships(user_id, brand["id"])
        assert listed[0]["episodes_together"] == 0

    def test_resolve_relationships_for_cast_includes_named_directions(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])
        culturetoons.create_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
            "relationship_type": "friendly_rivalry", "comedy_chemistry": 8,
            "a_to_b": {"affection_level": 7}, "b_to_a": {"affection_level": 6},
        })

        session = db()
        found = culturetoons.resolve_relationships_for_cast(session, brand["id"], [kumar["id"], hans["id"]])
        session.close()

        assert len(found) == 1
        assert found[0]["comedy_chemistry"] == 8
        directions = found[0]["directions"]
        assert len(directions) == 2
        kumar_to_hans = next(d for d in directions if d["from_character_id"] == kumar["id"])
        assert kumar_to_hans["from_character_name"] == kumar["name"]
        assert kumar_to_hans["to_character_name"] == "Hans"
        assert kumar_to_hans["affection_level"] == 7

    def test_generate_relationship_returns_draft_without_persisting(self, db, user_id, brand_and_character, mocker):
        from app.models.character_relationship import CharacterRelationship
        brand, kumar, _variant = brand_and_character
        hans = self._second_character(user_id, brand["id"])

        mock_generate = mocker.patch(
            "app.services.culturetoon_relationship.generate_relationship_dynamic",
            return_value={
                "relationship_type": "friendly_rivalry", "relationship_type_label": "Friendly Rivalry",
                "description": "A rivalry.", "comedy_chemistry": 8,
                "a_to_b": {"affection_level": 7, "trust_level": 8, "conflict_level": 6,
                           "perspective_description": "Hans takes rules too seriously.",
                           "behavior_rules": ["tries to persuade Hans"]},
                "b_to_a": {"affection_level": 6, "trust_level": 5, "conflict_level": 9,
                           "perspective_description": "Kumar creates unnecessary chaos.",
                           "behavior_rules": ["responds literally"]},
            },
        )

        draft = culturetoons.generate_relationship({
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": kumar["id"], "character_b_id": hans["id"],
        })

        assert draft["relationship_type"] == "friendly_rivalry"
        assert draft["a_to_b"]["affection_level"] == 7
        assert draft["b_to_a"]["affection_level"] == 6
        mock_generate.assert_called_once()

        session = db()
        assert session.query(CharacterRelationship).count() == 0  # never persisted
        session.close()

    def test_generate_relationship_requires_two_distinct_characters(self, db, user_id, brand_and_character):
        brand, kumar, _variant = brand_and_character
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.generate_relationship({
                "user_id": user_id, "brand_id": brand["id"],
                "character_a_id": kumar["id"], "character_b_id": kumar["id"],
            })
        assert exc_info.value.status_code == 400


class TestRelationshipEvents:
    def _second_character(self, user_id, brand_id, name="Hans"):
        return culturetoons.create_character({"user_id": user_id, "brand_id": brand_id, "name": name})

    def _relationship(self, user_id, brand, character, **overrides):
        hans = self._second_character(user_id, brand["id"])
        body = {
            "user_id": user_id, "brand_id": brand["id"],
            "character_a_id": character["id"], "character_b_id": hans["id"],
            "trust_level": 5, "affection_level": 5, "conflict_level": 5,
        }
        body.update(overrides)
        return culturetoons.create_relationship(body), hans

    def test_create_requires_valid_event_type(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, _hans = self._relationship(user_id, brand, character)
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship_event(rel["id"], {
                "user_id": user_id, "brand_id": brand["id"],
                "event_type": "not_a_real_type", "description": "Something happened",
            })
        assert exc_info.value.status_code == 400

    def test_create_requires_description(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, _hans = self._relationship(user_id, brand, character)
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship_event(rel["id"], {
                "user_id": user_id, "brand_id": brand["id"], "event_type": "general",
            })
        assert exc_info.value.status_code == 400

    def test_create_and_list_newest_first(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, _hans = self._relationship(user_id, brand, character)

        first = culturetoons.create_relationship_event(rel["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "event_type": "conflict", "description": "Argued over samosas",
        })
        second = culturetoons.create_relationship_event(rel["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "event_type": "reconciliation", "description": "Made up over chai",
        })
        assert first["event_type"] == "conflict"

        listed = culturetoons.list_relationship_events(rel["id"], user_id, brand["id"])
        assert [e["id"] for e in listed] == [second["id"], first["id"]]

    def test_deltas_applied_to_relationship_and_clamped(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, _hans = self._relationship(user_id, brand, character, trust_level=8, affection_level=2, conflict_level=5)

        culturetoons.create_relationship_event(rel["id"], {
            "user_id": user_id, "brand_id": brand["id"], "event_type": "betrayal",
            "description": "Hans threw Kumar under the bus in the meeting",
            "trust_delta": -5, "affection_delta": 9,  # would overflow past 10, must clamp
        })

        updated = culturetoons.list_relationships(user_id, brand["id"])[0]
        assert updated["trust_level"] == 3     # 8 - 5
        assert updated["affection_level"] == 10  # 2 + 9 = 11, clamped to 10

    def test_delta_must_be_within_range(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, _hans = self._relationship(user_id, brand, character)
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship_event(rel["id"], {
                "user_id": user_id, "brand_id": brand["id"], "event_type": "general",
                "description": "Extreme event", "trust_delta": 50,
            })
        assert exc_info.value.status_code == 400

    def test_delete_does_not_reverse_deltas(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, _hans = self._relationship(user_id, brand, character, trust_level=5)
        event = culturetoons.create_relationship_event(rel["id"], {
            "user_id": user_id, "brand_id": brand["id"], "event_type": "conflict",
            "description": "A big fight", "trust_delta": -3,
        })
        after_create = culturetoons.list_relationships(user_id, brand["id"])[0]
        assert after_create["trust_level"] == 2

        culturetoons.delete_relationship_event(event["id"], user_id, brand["id"])
        assert culturetoons.list_relationship_events(rel["id"], user_id, brand["id"]) == []
        after_delete = culturetoons.list_relationships(user_id, brand["id"])[0]
        assert after_delete["trust_level"] == 2  # unchanged — not an undo stack

    def test_wrong_brand_relationship_404s(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, _hans = self._relationship(user_id, brand, character)
        other_brand = culturetoons.create_brand({"user_id": user_id, "name": "Other Brand"})
        with pytest.raises(HTTPException) as exc_info:
            culturetoons.create_relationship_event(rel["id"], {
                "user_id": user_id, "brand_id": other_brand["id"],
                "event_type": "general", "description": "Shouldn't work",
            })
        assert exc_info.value.status_code == 404

    def test_resolve_relationships_for_cast_attaches_recent_events(self, db, user_id, brand_and_character):
        brand, character, _variant = brand_and_character
        rel, hans = self._relationship(user_id, brand, character)
        culturetoons.create_relationship_event(rel["id"], {
            "user_id": user_id, "brand_id": brand["id"],
            "event_type": "bonding", "description": "Shared an umbrella in the rain",
        })

        session = db()
        found = culturetoons.resolve_relationships_for_cast(session, brand["id"], [character["id"], hans["id"]])
        session.close()
        assert len(found) == 1
        assert len(found[0]["recent_events"]) == 1
        assert found[0]["recent_events"][0]["description"] == "Shared an umbrella in the rain"


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
