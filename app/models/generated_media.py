from sqlalchemy import Column, String, DateTime, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class GeneratedMedia(Base):
    __tablename__ = "generated_media"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_content_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    idea_index = Column(Integer, nullable=False)
    media_type = Column(String(20), nullable=False)   # voiceover|music|video
    provider = Column(String(30), nullable=False)     # elevenlabs|suno|kling
    status = Column(String(20), nullable=False, default="pending")  # pending|processing|done|failed
    prompt = Column(Text, nullable=True)
    asset_url = Column(Text, nullable=True)
    duration_seconds = Column(Numeric, nullable=True)
    cost_usd = Column(Numeric, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
