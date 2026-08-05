"""One-off manual smoke test of the CultureToons API against the real DB
and real providers (Qwen/Claude for shot-structured script suggestion,
Supabase Storage for image upload). Not a pytest test — run by hand:
    python scripts/live_test_culturetoons.py

Deliberately does NOT exercise register-element or generate-video — those
need real KLING_ACCESS_KEY/KLING_SECRET_KEY credentials available in this
local environment (see the plan's flagged open question: one live Kling
Omni call is needed to confirm the native-audio-speaks-dialogue hypothesis
before relying on it). This script covers everything that doesn't depend on
that: multi-brand creation, character/variant CRUD, image upload, and
shot-structured/tone-aware script generation from a real trending persona.
"""
import asyncio
import logging
import os
import sys
import uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("live_test_culturetoons")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from app.routers import culturetoons  # noqa: E402

# A minimal valid 1x1 PNG (transparent), enough to exercise the real upload path.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100"
    "0500010d0a2db40000000049454e44ae426082"
)


class _FakeUploadFile:
    def __init__(self, data: bytes, content_type: str):
        self._data = data
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


def main():
    user_id = str(uuid.uuid4())
    logger.info("Using throwaway smoke-test user_id=%s", user_id)

    brand_a = culturetoons.create_brand({"user_id": user_id, "name": "Smoke Test — Funny Clips"})
    brand_b = culturetoons.create_brand({"user_id": user_id, "name": "Smoke Test — Baby Videos"})
    logger.info("Created 2 brands for one user: %s / %s", brand_a["id"], brand_b["id"])
    assert len(culturetoons.list_brands(user_id)) == 2, "multi-brand-per-user did not work"

    brand = brand_a
    character = culturetoons.create_character({"user_id": user_id, "brand_id": brand["id"], "name": "Base Character"})
    logger.info("Character: %s", character)

    variant = culturetoons.create_variant({
        "user_id": user_id, "brand_id": brand["id"], "character_id": character["id"],
        "name": "Reality TV Fan Variant", "culture_tag": "test",
    })
    logger.info("Variant: %s", variant)

    upload_result = asyncio.run(culturetoons.upload_variant_image(
        variant["id"], user_id=user_id, brand_id=brand["id"], file=_FakeUploadFile(_TINY_PNG, "image/png"),
    ))
    logger.info("Variant image uploaded: %s", upload_result["image_url"])

    # Cross-brand isolation check — brand_b must not see brand_a's character.
    from fastapi import HTTPException
    try:
        culturetoons.get_variant(variant["id"], user_id, brand_b["id"])
        raise AssertionError("cross-brand lookup should have 404'd")
    except HTTPException as exc:
        assert exc.status_code == 404
    logger.info("Cross-brand isolation confirmed (404 as expected).")

    # Reuse persona 203 ("Reality TV Stan"), confirmed active earlier this session.
    script = culturetoons.suggest_script({
        "user_id": user_id, "brand_id": brand["id"], "source_type": "persona", "source_id": 203,
        "character_variant_id": variant["id"], "tone": "chaotic",
    })
    logger.info("AI-suggested shot-structured script: %s", script)
    assert script["shots"], "expected a non-empty shots list"
    assert script["tone"] == "chaotic"

    from app.services.culturetoon_script import build_kling_prompt
    dsl = build_kling_prompt(script["shots"], "TestElement")
    logger.info("Built Kling multi-shot DSL: %s", dsl)

    toon = culturetoons.create_toon({
        "user_id": user_id, "brand_id": brand["id"],
        "character_variant_id": variant["id"], "script_id": script["id"],
        "title": "Smoke test toon",
    })
    logger.info("Toon created: %s", toon)

    posted = culturetoons.update_toon(toon["id"], {
        "user_id": user_id, "brand_id": brand["id"], "status": "posted", "platform": "tiktok",
        "final_video_url": "https://example.com/smoke-test.mp4",
    })
    logger.info("Toon marked posted: %s", posted)

    assert posted["status"] == "posted"
    assert posted["posted_at"] is not None
    assert posted["final_video_url"] == "https://example.com/smoke-test.mp4"
    logger.info("SMOKE TEST PASSED (register-element / generate-video NOT covered — need real KLING_ACCESS_KEY/KLING_SECRET_KEY)")


if __name__ == "__main__":
    main()
