from sqlalchemy import Column, Integer, String, DateTime, ARRAY, Text, Time
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    target_age_min = Column(Integer, default=18)
    target_age_max = Column(Integer, default=35)
    target_platforms = Column(ARRAY(Text), default=list)
    target_regions = Column(ARRAY(Text), default=list)
    content_goals = Column(ARRAY(Text), default=list)
    content_tones = Column(ARRAY(Text), default=list)
    industry_niche = Column(Text, nullable=True)
    persona_tags = Column(ARRAY(Text), default=list)
    delivery_freq = Column(String(10), default="daily")
    delivery_time = Column(Text, default="07:00")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
