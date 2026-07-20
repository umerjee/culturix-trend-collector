from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, BigInteger

from app.db import Base


class HighVelocityAlert(Base):
    """Recorded whenever the scraping/ velocity pipeline (culturix_scraping.hooks.
    trigger_content_engine) sees an item cross VELOCITY_THRESHOLD and POSTs it to
    CONTENT_ENGINE_WEBHOOK_URL. Deliberately just a record, not a pipeline trigger —
    see app/main.py's high_velocity_trend_webhook for why."""
    __tablename__ = "high_velocity_alerts"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(20), nullable=False, index=True)
    external_id = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    velocity_score = Column(Float, nullable=False)
    like_count = Column(Integer, nullable=True)
    view_count = Column(BigInteger, nullable=True)
    trend_posted_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
