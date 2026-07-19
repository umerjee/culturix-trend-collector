from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime
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
    # Which Cluster this persona was generated from — lets generate_clustered_personas
    # skip clusters that already have a persona instead of regenerating every run.
    cluster_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    trends = relationship("TrendPersona", back_populates="persona")
