from sqlalchemy import Column, String, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonBackground(Base):
    """A reusable background image belonging to a CharacterBrand (not to any
    one Character — backgrounds are meant to be rotated across characters,
    per the brand's own scaling strategy)."""
    __tablename__ = "toon_backgrounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    image_url = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)  # comma-separated, matches ShopifyProduct.tags
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
