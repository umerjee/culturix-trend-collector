from sqlalchemy import Column, Integer, String, DateTime, ARRAY, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ContentProfile(Base):
    __tablename__ = "content_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(120), nullable=False, default="My Profile")
    industry_niche = Column(Text, nullable=True)
    target_platforms = Column(ARRAY(Text), default=list)
    target_regions = Column(ARRAY(Text), default=list)
    content_goals = Column(ARRAY(Text), default=list)
    content_tones = Column(ARRAY(Text), default=list)
    persona_tags = Column(ARRAY(Text), default=list)
    target_age_min = Column(Integer, default=18)
    target_age_max = Column(Integer, default=35)
    delivery_freq = Column(String(10), default="daily")
    delivery_time = Column(Text, default="07:00")
    # 0=Monday..6=Sunday (matches date.weekday(), same convention as
    # trend_historian.py's dominant_day_of_week). Only meaningful when
    # delivery_freq == "weekly"; ignored for "daily".
    delivery_day_of_week = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True)
    publish_mode = Column(String(10), nullable=False, default="manual")  # manual|review|auto
    # video|photo|text — empty/unset means "no restriction" (all three), resolved
    # in content_strategist.py rather than the DB default, so existing profiles
    # created before this field existed keep behaving exactly as before.
    preferred_formats = Column(ARRAY(Text), default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
