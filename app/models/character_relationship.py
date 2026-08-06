from sqlalchemy import Column, String, DateTime, Text, Integer, Boolean, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CharacterRelationship(Base):
    """A persistent, directionless relationship between two base Characters
    within one CharacterBrand — e.g. "Kumar and Hans have a friendly
    rivalry." Character-level, not CharacterVariant-level (decided against
    variant-level: one relationship applies regardless of which cultural
    variant of a character is cast — see docs/culturix-comedy-architecture.md
    §3.4/decision 5). Asymmetric perspective ("Imran thinks Hans is rigid,
    Hans thinks Imran is chaotic") lives inside description/behavioral_rules
    as text, not as two separate directional rows.

    Injected into script generation (culturetoon_script.py) whenever a
    script's cast includes both character_a_id and character_b_id, resolved
    from each cast CharacterVariant.character_id — see
    culturetoon_relationships.py::resolve_relationships_for_cast."""
    __tablename__ = "character_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    character_a_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    character_b_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=True)  # e.g. friendly_rivalry, siblings, colleagues
    description = Column(Text, nullable=True)
    emotional_dynamic = Column(Text, nullable=True)
    conflict_level = Column(Integer, nullable=True)   # 0-10, low=harmonious, high=combative
    trust_level = Column(Integer, nullable=True)       # 0-10, low=suspicious, high=trusting
    humor_dynamic = Column(Text, nullable=True)
    behavioral_rules = Column(ARRAY(Text), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
