from datetime import datetime

from sqlalchemy import Column, Integer, DateTime, Date, ForeignKey, UniqueConstraint

from app.db import Base


class PersonaOccurrence(Base):
    """One row per calendar day a Persona archetype was seen in an approved
    cluster — structural mirror of TrendOccurrence's role for TrendTheme.
    cluster_id is nullable because clusterer.py's clusters are transient
    (never persisted to a browsable table); recorded when available for
    admin drill-down, not required for recurrence/momentum computation."""
    __tablename__ = "persona_occurrences"
    __table_args__ = (
        UniqueConstraint("persona_id", "occurrence_date", name="uq_persona_occurrence_persona_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False, index=True)
    cluster_id = Column(Integer, nullable=True)
    occurrence_date = Column(Date, nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False, index=True)  # denormalized from occurrence_date
    created_at = Column(DateTime, default=datetime.utcnow)
