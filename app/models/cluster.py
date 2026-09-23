from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, JSON

from app.db import Base


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    # Label assigned by HDBSCAN (-1 = noise, 0+ = cluster index)
    label = Column(Integer, nullable=False, index=True)
    # Human-readable theme inferred from the cluster's trends
    theme = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    # Cached Voyage.ai embedding of this cluster's own theme+summary, used
    # ONLY for CultureToons' trend-relevance ranking — see
    # app/services/culturetoon_trend_relevance.py.
    relevance_embedding = Column(JSON, nullable=True)
    # Number of trends in this cluster
    size = Column(Integer, nullable=True)
    # Average pairwise cosine similarity of this cluster's trend embeddings —
    # informational tightness metric only, computed by
    # app.services.trend_quality.compute_cohesion inside run_clustering (embeddings
    # are already loaded there). NOT part of quality_score: a cluster of near-
    # identical spam posts is highly cohesive by this measure, so cohesion alone
    # can't distinguish "one real theme" from "one repeated post" — see
    # trend_quality.py's module docstring. Was dead (100% NULL) before that wiring.
    cohesion = Column(Float, nullable=True)
    # 0.0-1.0 composite from app.services.trend_quality.score_group (persistence +
    # cross-platform corroboration + textual diversity + size), computed and
    # persisted by run_clustering. Consumers needing a fresh value for a specific
    # trend set (e.g. the world trends digest, which also scores raw unclustered
    # buckets on the same scale) call score_group directly rather than reading
    # this column — it exists for admin visibility and future backtesting
    # (quality_components carries the weights_version for that).
    quality_score = Column(Float, nullable=True)
    quality_components = Column(JSON, nullable=True)
    quality_computed_at = Column(DateTime, nullable=True)
    # Hash of this cluster's trend id membership — lets run_clustering reuse
    # (and skip re-labeling) clusters whose membership hasn't changed.
    fingerprint = Column(String(64), nullable=True, index=True)
    # Trend direction vs the last time a significantly-overlapping cluster
    # was seen: 'up' | 'down' | 'neutral' | NULL (no prior history yet).
    momentum = Column(String(10), nullable=True)
    previous_size = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
