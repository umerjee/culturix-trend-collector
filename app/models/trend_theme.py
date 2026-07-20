from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, JSON

from app.db import Base


class TrendTheme(Base):
    """Canonical, persistent identity for a trend across days. Cluster naming is a fresh
    LLM call every pipeline run, so 'today's cluster' is matched back to a theme by
    embedding similarity (see trend_historian.py) rather than exact name matching."""
    __tablename__ = "trend_themes"

    id = Column(Integer, primary_key=True, index=True)
    canonical_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    emotional_theme = Column(String, nullable=True)
    # Running-average embedding of this theme's occurrences — what new clusters are compared against
    centroid_embedding = Column(JSON, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    occurrence_count = Column(Integer, nullable=False, default=0)
    # 0=Monday .. 6=Sunday, only meaningful once recurrence_pattern == 'weekly'
    dominant_day_of_week = Column(Integer, nullable=True)
    recurrence_pattern = Column(String(20), nullable=True)  # weekly | yearly | sustained | spike | unclear
    pattern_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
