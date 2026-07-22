from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime

from app.db import Base


class IntegrationHealth(Base):
    """Tracks periodic health checks for unofficial/no-SLA third-party
    integrations (edge-tts, Twitter's Jina/trends24.in proxy) that have no
    guaranteed uptime and can silently break on an upstream change — see
    app/integration_health.py for the checks themselves."""
    __tablename__ = "integration_health"

    id = Column(Integer, primary_key=True, index=True)
    integration_name = Column(String(50), nullable=False, index=True)  # "edge_tts" | "twitter_proxy"
    status = Column(String(10), nullable=False)  # "healthy" | "unhealthy"
    error = Column(Text, nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow, index=True)
