from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float

from app.db import Base


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    # Label assigned by HDBSCAN (-1 = noise, 0+ = cluster index)
    label = Column(Integer, nullable=False, index=True)
    # Human-readable theme inferred from the cluster's trends
    theme = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    # Number of trends in this cluster
    size = Column(Integer, nullable=True)
    # Average cohesion score (optional quality metric)
    cohesion = Column(Float, nullable=True)
    # Hash of this cluster's trend id membership — lets run_clustering reuse
    # (and skip re-labeling) clusters whose membership hasn't changed.
    fingerprint = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
