from datetime import datetime

from sqlalchemy import Column, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.db import Base


class TrendPersona(Base):
    __tablename__ = "trend_personas"

    id = Column(Integer, primary_key=True, index=True)
    trend_id = Column(Integer, ForeignKey("trends.id"), nullable=False)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False)
    confidence = Column(Float, default=1.0)

    # These strings avoid circular imports
    persona = relationship("Persona", back_populates="trends")
    trend = relationship("Trend", back_populates="personas")
