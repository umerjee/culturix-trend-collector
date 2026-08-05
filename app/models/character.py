from sqlalchemy import Column, String, DateTime, Text, Boolean
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
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
