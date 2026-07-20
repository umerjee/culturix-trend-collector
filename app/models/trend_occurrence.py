from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, UniqueConstraint

from app.db import Base


class TrendOccurrence(Base):
    """One row per calendar day a TrendTheme was seen — the raw time series that
    recurrence_pattern/dominant_day_of_week get computed from."""
    __tablename__ = "trend_occurrences"
    __table_args__ = (
        UniqueConstraint("theme_id", "occurrence_date", name="uq_trend_occurrence_theme_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    theme_id = Column(Integer, ForeignKey("trend_themes.id"), nullable=False, index=True)
    occurrence_date = Column(Date, nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False, index=True)  # denormalized from occurrence_date
    name_snapshot = Column(Text, nullable=True)
    description_snapshot = Column(Text, nullable=True)
    size = Column(Integer, nullable=True)
    durability = Column(String(20), nullable=True)  # sustained | spike | unclear, from trend_validator
    created_at = Column(DateTime, default=datetime.utcnow)
