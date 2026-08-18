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

    # Self-hosted (RunPod Serverless + ComfyUI + LTX-2) video generation's
    # own character-consistency mechanism — a trained LoRA, analogous to
    # kling_element_id/element_status above but for the self-hosted path
    # instead of Kling Omni. See app/services/culturetoon_lora.py /
    # app/services/culturetoon_selfhosted_video.py. Independent of the Kling
    # Element fields — a variant can have either, both, or neither ready,
    # since the two video paths are separate and this is the self-hosted
    # one's own identity mechanism.
    #
    # A bare filename (e.g. "<variant-id>.safetensors"), NOT a URL — under
    # the Network-Volume architecture, training writes the LoRA directly
    # into the shared volume's ComfyUI/models/loras/ directory that the
    # Serverless inference endpoint also mounts, so the file never needs to
    # leave the volume and this just needs to be whatever ComfyUI's
    # LoraLoader node resolves it by.
    lora_path = Column(Text, nullable=True)
    lora_status = Column(String(12), nullable=False, default="none")  # none|training|ready|failed
    # List of {"url": str, "caption": str} — NOT a bare URL array. A LoRA
    # trained on identically-captioned images overfits to whatever's
    # constant across them (a pose, a background) instead of learning the
    # character's actual identity; ltx-trainer's own dataset format is
    # video+caption pairs (see culturetoon_lora.py's module docstring), so
    # each image needs its own real caption of what's actually in THAT
    # image, not a repeated character name. Captioned automatically at
    # upload time (culturetoon_lora.py::caption_training_image) so this
    # data is ready before /train-lora is ever called, not discovered
    # missing at training time.
    lora_training_images = Column(JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
