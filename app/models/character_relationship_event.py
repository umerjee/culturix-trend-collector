from sqlalchemy import Column, String, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CharacterRelationshipEvent(Base):
    """A single timestamped entry in a CharacterRelationship's history — what
    actually happened between the two characters, distinct from the
    relationship's own static current-state fields (trust_level/
    conflict_level/affection_level). Also distinct from CharacterMemory,
    which is per-CharacterVariant and semantically retrieved via Qdrant —
    this is per-relationship-pair and small enough in volume that a plain
    "most recent N, newest first" query is enough; no embedding involved.
    See docs/culturix-character-studio-upgrade.md §4 Phase 2.

    The *_delta fields, when set on creation, are applied once to the
    parent relationship's current levels (clamped 0-10) so a logged event
    is consequential, not just narrative flavor — see
    app/routers/culturetoons.py::create_relationship_event. Deleting an
    event does not reverse its delta, the same way deleting a journal entry
    doesn't rewind history — this is a log, not an undo stack.

    Injected into script generation (as each relationship's `recent_events`,
    attached in resolve_relationships_for_cast) so scripts can reference
    the trajectory of a relationship, not just its current snapshot."""
    __tablename__ = "character_relationship_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    relationship_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)  # conflict|bonding|running_joke|betrayal|reconciliation|milestone|general
    description = Column(Text, nullable=False)
    affection_delta = Column(Integer, nullable=True)  # -10..10, applied once at creation
    trust_delta = Column(Integer, nullable=True)
    conflict_delta = Column(Integer, nullable=True)
    source_toon_id = Column(UUID(as_uuid=True), nullable=True)
    source_episode_id = Column(UUID(as_uuid=True), nullable=True)
    source_scene_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
