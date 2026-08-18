from sqlalchemy import Column, String, DateTime, Text, Boolean, JSON, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class Character(Base):
    """A base character concept (the un-morphed rig/design), belonging to
    one CharacterBrand. Cultural variants of this base live in
    CharacterVariant — see app/models/character_variant.py."""
    __tablename__ = "characters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    base_image_url = Column(Text, nullable=True)
    # The user's raw uploaded photo (if any), kept distinct from
    # base_image_url so repeated AI-generation iterations always ground on
    # the same source photo instead of compounding drift by re-generating
    # from the previous generation's own output.
    reference_image_url = Column(Text, nullable=True)
    # Regenerating base_image_url used to silently discard the prior
    # portrait, same trap as Toon.raw_video_url before previous_video_urls
    # was added — see docs/culturix-comedy-architecture.md §3.3.
    previous_image_urls = Column(ARRAY(Text), nullable=True)
    # Which illustrated art style AI image generation renders this character
    # (and, by default, its variants) into — see ART_STYLES in
    # app/routers/culturetoons.py. Without an explicit style instruction in
    # the prompt, a supplied reference photo tends to just get lightly
    # re-touched rather than actually re-illustrated as a cartoon.
    art_style = Column(String(30), nullable=False, default="cartoon_3d")
    # Structured personality — {"traits": {name: 0-1 float, ...},
    # "behavioral_rules": [str, ...], "speech_rules": [str, ...]}, validated
    # at the API boundary (app/routers/culturetoons.py), not DB-constrained.
    # Consumed by culturetoon_script.py's prompt builder so character
    # identity is deterministic across scripts rather than re-improvised by
    # the LLM each time — see docs/culturix-comedy-architecture.md §3.2.
    personality = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # At most one per brand — the anchor character a story/cast is built
    # around. Auto-set on a brand's first character (see create_character),
    # reassignable afterward via PUT /characters/{id}. Enforced server-side,
    # not by a DB constraint (this codebase has no migration framework for
    # cross-row constraints — see app/main.py's lifespan()).
    is_main = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
