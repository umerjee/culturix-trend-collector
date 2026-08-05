"""One-off manual smoke test of the CultureToons API against the real DB
and real providers (Qwen/Claude for script suggestion, Supabase Storage for
the image upload). Not a pytest test — run by hand:
    python scripts/live_test_culturetoons.py
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

    brand = culturetoons.upsert_brand({"user_id": user_id, "name": "Smoke Test Brand"})
    logger.info("Brand: %s", brand)

    character = culturetoons.create_character({"user_id": user_id, "name": "Base Character"})
    logger.info("Character: %s", character)

    variant = culturetoons.create_variant({
        "user_id": user_id, "character_id": character["id"],
        "name": "Reality TV Fan Variant", "culture_tag": "test",
    })
    logger.info("Variant: %s", variant)

    upload_result = asyncio.run(culturetoons.upload_variant_image(
        variant["id"], user_id=user_id, file=_FakeUploadFile(_TINY_PNG, "image/png"),
    ))
    logger.info("Variant image uploaded: %s", upload_result["image_url"])

    # Reuse persona 203 ("Reality TV Stan"), confirmed active earlier this session.
    script = culturetoons.suggest_script({
        "user_id": user_id, "source_type": "persona", "source_id": 203,
        "character_variant_id": variant["id"],
    })
    logger.info("AI-suggested script: %s", script)

    toon = culturetoons.create_toon({
        "user_id": user_id, "character_variant_id": variant["id"], "script_id": script["id"],
        "title": "Smoke test toon",
    })
    logger.info("Toon created: %s", toon)

    posted = culturetoons.update_toon(toon["id"], {
        "user_id": user_id, "status": "posted", "platform": "tiktok",
        "final_video_url": "https://example.com/smoke-test.mp4",
    })
    logger.info("Toon marked posted: %s", posted)

    assert posted["status"] == "posted"
    assert posted["posted_at"] is not None
    assert posted["final_video_url"] == "https://example.com/smoke-test.mp4"
    logger.info("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
