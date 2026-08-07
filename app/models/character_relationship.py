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
    culturetoon_relationships.py::resolve_relationships_for_cast.

    relationship_type/conflict_level/trust_level/affection_level/
    humor_dynamic/behavioral_rules below are the ORIGINAL symmetric fields,
    kept for backward compatibility (existing rows, CharacterRelationshipEvent's
    delta application) — as of the directional refinement, per-direction
    affection/trust/conflict/perspective/behavior now live on
    CharacterRelationshipDirection (two rows per relationship, one each
    way) and are what new UI/script-generation actually reads. description
    below is the relationship's general/neutral description; each
    direction's own perspective_description is separate. See
    app/models/character_relationship_direction.py."""
    __tablename__ = "character_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    character_a_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    character_b_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=True)  # machine-readable enum key, e.g. friendly_rivalry — or "custom"
    # Human-readable label — the enum's canonical label, or the user's own
    # text when relationship_type="custom". See _RELATIONSHIP_TYPES in
    # app/routers/culturetoons.py for the fixed set.
    relationship_type_label = Column(String(80), nullable=True)
    description = Column(Text, nullable=True)  # general/neutral description of the pair
    # 0-10 — how naturally this pair generates humorous interactions; used
    # by future episode/scene idea generation to pick high-performing casts.
    comedy_chemistry = Column(Integer, nullable=True)
    emotional_dynamic = Column(Text, nullable=True)
    conflict_level = Column(Integer, nullable=True)   # legacy symmetric field, see class docstring
    trust_level = Column(Integer, nullable=True)       # legacy symmetric field, see class docstring
    affection_level = Column(Integer, nullable=True)   # legacy symmetric field, see class docstring
    humor_dynamic = Column(Text, nullable=True)
    behavioral_rules = Column(ARRAY(Text), nullable=True)  # legacy symmetric field, see class docstring
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
