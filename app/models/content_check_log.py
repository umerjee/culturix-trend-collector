from sqlalchemy import Column, String, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ContentCheckLog(Base):
    __tablename__ = "content_check_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_content_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    idea_index = Column(Integer, nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)
    previous_score = Column(Integer, nullable=True)
    new_score = Column(Integer, nullable=False)
    trend_score = Column(Integer, nullable=True)
    freshness_score = Column(Integer, nullable=True)
    persona_score = Column(Integer, nullable=True)
    previous_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=False)
    action_taken = Column(Text, nullable=True)
