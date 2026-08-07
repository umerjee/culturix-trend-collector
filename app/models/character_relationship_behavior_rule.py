from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CharacterRelationshipBehaviorRule(Base):
    """One directional behavior rule, e.g. "tries to persuade Hans to bend
    rules" (Kumar -> Hans). Scoped to a single CharacterRelationshipDirection
    (not the relationship itself, which has no inherent direction) — a
    replacement for the old CharacterRelationship.behavioral_rules array,
    which couldn't express that Kumar's rules toward Hans differ from
    Hans's rules toward Kumar. Whole-list-replace on edit (delete this
    direction's rows, insert the new set), same semantics the old array
    column had, just now structured records instead of a single array."""
    __tablename__ = "character_relationship_behavior_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    relationship_direction_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    rule_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
