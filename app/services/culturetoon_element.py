"""Registers a CharacterVariant as a Kling Element (+ optionally a bound
voice) so it can be cheaply referenced (@ElementName) in every future video
generation instead of re-establishing the character's visual/voice identity
each time. Mirrors app/shopify/reels.py::generate_reel_for_product's shape
(load row -> set in-progress status -> do slow async work -> write result
back -> catch-and-record-error -> finally: session.close()).
"""
import logging

logger = logging.getLogger("culturix.services.culturetoon_element")


def _sanitize_element_name(name: str) -> str:
    return (name or "Character").strip()[:20] or "Character"


def _dedupe_element_name(session, brand_id, exclude_character_id, candidate: str) -> str:
    """Kling requires element names not be substrings of one another within
    the scope they're used together. Disambiguates against every other
    variant already registered under this brand by appending a short numeric
    suffix (truncated to still fit the 20-char cap) until no substring
    conflict remains."""
    from app.models.character import Character
    from app.models.character_variant import CharacterVariant

    character_ids = [
        c.id for c in session.query(Character.id).filter_by(brand_id=brand_id).all()
    ]
    existing = {
        row.kling_element_name
        for row in session.query(CharacterVariant.kling_element_name)
        .filter(CharacterVariant.character_id.in_(character_ids))
        .filter(CharacterVariant.kling_element_name.isnot(None))
        .filter(CharacterVariant.character_id != exclude_character_id)
        .all()
    }

    def conflicts(name: str) -> bool:
        return any(name in other or other in name for other in existing)

    if not conflicts(candidate):
        return candidate

    for suffix in range(2, 100):
        suffix_str = f"-{suffix}"
        trimmed = candidate[: 20 - len(suffix_str)] + suffix_str
        if not conflicts(trimmed):
            return trimmed

    raise ValueError(f"Could not find a non-conflicting element name for '{candidate}' after 98 attempts")


def register_character_variant(user_id, brand_id, variant_id, refer_image_urls=None,
                                voice_sample_url=None, preset_voice_id=None,
                                voice_provider="kling", elevenlabs_voice_id=None) -> None:
    from app.db import SessionLocal
    from app.models.character_variant import CharacterVariant
    from app.media.kling_omni import KlingOmniProvider, KlingOmniError

    session = SessionLocal()
    variant = None
    try:
        variant = session.query(CharacterVariant).filter_by(id=variant_id).first()
        if not variant:
            raise ValueError("Character variant not found")
        if not variant.image_url:
            raise ValueError("Variant has no image to register as a Kling element — upload one first")

        variant.element_status = "pending"
        variant.element_error = None
        variant.voice_provider = voice_provider
        variant.elevenlabs_voice_id = elevenlabs_voice_id
        session.commit()

        # ElevenLabs-voiced characters don't need a Kling-bound voice at all —
        # Kling still needs the visual Element for character consistency, but
        # dialogue audio for these characters is synthesized separately (see
        # app/services/culturetoon_video.py) and muxed in afterward.
        provider = KlingOmniProvider()
        kling_voice_id = None
        if voice_provider != "elevenlabs":
            if voice_sample_url:
                kling_voice_id = provider.create_voice(f"{variant.name[:15]}-voice", voice_sample_url)
            elif preset_voice_id:
                kling_voice_id = preset_voice_id

        element_name = _dedupe_element_name(
            session, brand_id, variant.character_id, _sanitize_element_name(variant.name)
        )
        element_id = provider.create_element(
            element_name=element_name,
            element_description=(variant.description or variant.culture_tag or variant.name)[:100],
            frontal_image_url=variant.image_url,
            refer_image_urls=refer_image_urls,
            voice_id=kling_voice_id,
        )

        variant.kling_element_id = element_id
        variant.kling_element_name = element_name
        variant.kling_voice_id = kling_voice_id
        variant.element_status = "ready"
        session.commit()
        logger.info("Registered Kling element %s for variant %s", element_id, variant_id)

    except (ValueError, KlingOmniError) as exc:
        session.rollback()
        if variant:
            variant.element_status = "failed"
            variant.element_error = str(exc)[:2000]
            session.commit()
        logger.error("Element registration failed for variant %s: %s", variant_id, exc)
    except Exception as exc:
        session.rollback()
        if variant:
            variant.element_status = "failed"
            variant.element_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Element registration failed unexpectedly for variant %s", variant_id)
    finally:
        session.close()
