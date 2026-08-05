from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
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
    description = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    persona_id = Column(Integer, nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
