from sqlalchemy import Column, String, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CharacterMemory(Base):
    """A persistent fact/event tied to one CharacterVariant (not the base
    Character — a specific cultural variant's own running joke or
    established fact isn't necessarily true of a sibling variant of the
    same base character). Retrieved via semantic search (Qdrant, reusing
    the same Voyage.ai embedding infra the trend engine already uses — see
    app/services/culturetoon_memory.py) and injected into script generation
    so future episodes can reference what already happened instead of
    starting cold each time. See docs/culturix-comedy-architecture.md §3.5."""
    __tablename__ = "character_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_variant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    memory_type = Column(String(30), nullable=False)  # backstory|recurring_fact|relationship_event|
                                                         # previous_joke|preference|running_gag|episode_event
    content = Column(Text, nullable=False)
    importance = Column(Integer, nullable=True)  # 0-10, optional
    source_toon_id = Column(UUID(as_uuid=True), nullable=True)  # which Toon this memory came from, if any
    created_at = Column(DateTime, default=datetime.utcnow)
