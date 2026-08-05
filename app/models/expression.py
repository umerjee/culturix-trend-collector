from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class Expression(Base):
    """One of a CharacterVariant's 10 reusable expressions (Angry, Confused,
    Happy, Shocked, Laughing, Side-eye, Crying, Annoyed, Smiling, Deadpan —
    see EXPRESSION_NAMES in app/routers/culturetoons.py, the actual
    validated allow-list; not a DB enum, same soft-enum convention as
    Persona.status)."""
    __tablename__ = "expressions"
    __table_args__ = (
        UniqueConstraint("character_variant_id", "name", name="uq_expressions_variant_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_variant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(30), nullable=False)
    image_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
