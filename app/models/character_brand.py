from sqlalchemy import Column, String, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CharacterBrand(Base):
    """One row per user's CultureToons brand/workspace — one per user for
    now (v1 beta scope), mirroring ShopifyStore's "one store per user"
    convention. Owns Characters, Backgrounds, Scripts, and Toons."""
    __tablename__ = "character_brands"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    name = Column(String(120), nullable=False, default="My CultureToons Brand")
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
