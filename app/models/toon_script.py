from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonScript(Base):
    """A short (10-15s) punchy skit script for a CultureToons brand:
    hook_line + dialogue + scene_direction (e.g. "Cut to: 12 dishes.").
    Optionally FK'd to a CharacterVariant it was written for, and optionally
    grounded in a trending Persona or Cluster via source_type/source_id —
    mirrors Clip's exact source_type/source_id pattern (app/models/clip.py):
    source_id is Integer since Persona.id/Cluster.id are Integer, not UUID.
    Both source fields are NULL for a hand-authored script."""
    __tablename__ = "toon_scripts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    character_variant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    source_type = Column(String(10), nullable=True, index=True)  # persona|cluster|NULL
    source_id = Column(Integer, nullable=True, index=True)
    hook_line = Column(Text, nullable=True)
    dialogue = Column(Text, nullable=True)
    scene_direction = Column(Text, nullable=True)
    generation_source = Column(String(10), nullable=False, default="manual")  # manual|ai
    status = Column(String(12), nullable=False, default="draft")  # draft|approved|archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
