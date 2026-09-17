from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import uuid
from app.db import Base


class CharacterVariant(Base):
    """A cultural morph of a base Character (e.g. "Indian Mom", "Nigerian
    Uncle"), each with its own reference image and its own 10 Expression
    rows (see app/models/expression.py). persona_id is an optional link to
    an existing trend Persona this variant represents — Integer, not UUID,
    since Persona.id is an Integer primary key."""
    __tablename__ = "character_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    culture_tag = Column(String(60), nullable=True)
    # Optional link into the shared Culture library (app/models/culture.py)
    # for structured social/comedy context in script generation — falls
    # back to the free-text culture_tag above when unset (a culture not
    # yet in the library, or a user who just wants to type something
    # quick). See docs/culturix-comedy-architecture.md §3.7.
    culture_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    description = Column(Text, nullable=True)
    # User-editable accent/vocal tone/pacing reference — separate from
    # `description` above (visual appearance/personality). Added 2026-09-03
    # because self-hosted LTX-2.5 generates audio and video JOINTLY (see
    # app/services/culturetoon_selfhosted_video.py's module docstring), so a
    # character's voice is as real an identity trait as their face, but
    # until now the render's voice instruction was auto-derived from
    # `description` with no user-facing control at all — confirmed live
    # (2026-09-02/03) a wrong or ambiguous accent can't be fixed without
    # rewriting the whole appearance description. Falls back to `description`
    # in the render prompt when left blank, so this is purely additive.
    voice_description = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    # A variant-specific raw reference photo, if the user has one (e.g. a
    # real photo for the "Wife" variant). Optional — when absent, AI image
    # generation for this variant grounds on the base Character's own
    # base_image_url instead, so a variant with no photo of its own still
    # inherits the character's already-established illustrated look.
    reference_image_url = Column(Text, nullable=True)
    # Same regeneration-history reasoning as Character.previous_image_urls.
    previous_image_urls = Column(ARRAY(Text), nullable=True)
    persona_id = Column(Integer, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Kling Element registration — created once from image_url, then reused
    # cheaply across every future video generation via @kling_element_name
    # instead of re-establishing the character's identity each time. See
    # app/media/kling_omni.py / app/services/culturetoon_element.py.
    kling_element_id = Column(String(64), nullable=True)
    kling_element_name = Column(String(20), nullable=True)  # Kling's own 20-char cap; sanitized/deduped copy of `name`
    kling_voice_id = Column(String(64), nullable=True)       # Kling-cloned or preset voice bound to the element
    element_status = Column(String(12), nullable=False, default="unregistered")  # unregistered|pending|ready|failed
    element_error = Column(Text, nullable=True)
    element_task_id = Column(String(64), nullable=True)      # Kling's async create-element task_id, kept for debugging/retry
    voice_task_id = Column(String(64), nullable=True)

    # Optional per-character override: use the brand's ElevenLabs credential
    # (CharacterBrand.elevenlabs_api_key_encrypted) instead of Kling's native
    # voice for this specific character's dialogue.
    voice_provider = Column(String(12), nullable=False, default="kling")  # kling|elevenlabs
    elevenlabs_voice_id = Column(String(64), nullable=True)  # only meaningful when voice_provider="elevenlabs"

    # Bulk "Generate all expressions" tracking (POST /variants/{id}/
    # expressions/generate-all) — backgrounded the same way element
    # registration above is, since 10 sequential paid image-generation
    # calls run well past any HTTP gateway's timeout (confirmed live: a
    # synchronous version of this got killed mid-batch by Vercel's own
    # serverless function execution limit, independent of anything the
    # client-side fetch allowed). The frontend polls while
    # expressions_generating is true, same shape as element_status
    # polling. expressions_generate_errors holds the last run's
    # {name: error} map (not a running log) — cleared at the start of
    # each new run, read once generating flips back to false.
    expressions_generating = Column(Boolean, nullable=False, default=False)
    expressions_generate_errors = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
