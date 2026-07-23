from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import relationship

from app.db import Base


class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    motivations = Column(Text, nullable=True)
    interests = Column(Text, nullable=True)
    content_suggestions = Column(Text, nullable=True)
    # Legacy-only — 1:1 link from the old (superseded 2026-07-23) per-cluster
    # generation path. Rows created by app/pipeline/nodes/persona_tag_tracker.py
    # leave this null and use PersonaOccurrence instead, since a persona archetype
    # now recurs across many clusters over many days rather than mapping to one.
    cluster_id = Column(Integer, nullable=True, index=True)

    # Cross-day recurrence tracking (mirrors TrendTheme's shape/role) — see
    # app/pipeline/nodes/persona_tag_tracker.py.
    centroid_embedding = Column(JSON, nullable=True)
    status = Column(String(10), nullable=False, default="pending")  # pending|active|dormant
    momentum = Column(String(10), nullable=True)  # up|down|neutral, same vocabulary as Cluster.momentum
    occurrence_count = Column(Integer, nullable=False, default=0)
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    trends = relationship("TrendPersona", back_populates="persona")
    # No relationship() to PersonaOccurrence, deliberately — same convention
    # as TrendTheme/TrendOccurrence (plain FK, queried manually), which
    # avoids a cross-model mapper-configuration dependency that would
    # otherwise break anywhere Persona is imported without PersonaOccurrence.
