from sqlalchemy import Column, Integer, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CharacterRelationshipDirection(Base):
    """One character's dynamic TOWARD the other within a CharacterRelationship
    — personality toward another character is not necessarily symmetrical
    (Kumar may trust Hans more than Hans trusts Kumar), so affection/trust/
    conflict/behavior/perspective all live here, one row per direction, not
    on CharacterRelationship itself.

    Exactly two rows per relationship (from_character_id=A/to=B, and
    from=B/to=A) — created together whenever a CharacterRelationship is
    created, never independently, and never duplicated (see the unique
    constraint below). This does NOT create a second relationship record;
    CharacterRelationship stays the single row for the pair (relationship
    type, general description, comedy_chemistry) — see docs/culturix-
    relationship-refinement.md.

    Structured behavioral rules live in a separate table
    (CharacterRelationshipBehaviorRule), not an array column here, per the
    explicit ask to store them as distinct records rather than a single
    concatenated string."""
    __tablename__ = "character_relationship_directions"
    __table_args__ = (
        UniqueConstraint("relationship_id", "from_character_id", name="uq_relationship_direction_from"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    relationship_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # denormalized, same pattern as other child tables
    from_character_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    to_character_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    affection_level = Column(Integer, nullable=True)   # 0-10
    trust_level = Column(Integer, nullable=True)        # 0-10
    conflict_level = Column(Integer, nullable=True)     # 0-10, "conflict/annoyance"
    # from_character's own perspective on to_character, e.g. "Hans takes
    # rules too seriously." Distinct from CharacterRelationship.description,
    # which is the neutral/general description of the pair.
    perspective_description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
