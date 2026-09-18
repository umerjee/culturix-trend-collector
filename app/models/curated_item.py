from sqlalchemy import Column, String, DateTime, Integer, Float, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CuratedItem(Base):
    """One row per item produced by the Culturix Ingestion & Validation
    Engine (app/services/culturix_ingestion.py) — the scored/curated layer
    downstream of raw ingestion, same relationship content_check_log has to
    GeneratedContent, but a first-class table since this engine's output
    needs its own lifecycle fields (expires_at etc.) that don't fit
    naturally into an existing row.

    Deliberately separate from `trends` (app/models/trend.py) — `trends`
    stays the raw, unscored social-signal layer exactly as it already is;
    this table is real curated output: extracted, classified, scored,
    challenged, and given a decision + lifecycle, from real sources
    (Wikipedia article extracts, UNESCO World Heritage data, or a batch of
    existing Trend rows for a region) — never fabricated content."""
    __tablename__ = "curated_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Where this came from and how to re-fetch/dedup it — source_ref is the
    # Wikipedia page title, UNESCO id_no, or a Trend.id (as a string),
    # depending on source_type.
    source_type = Column(String(20), nullable=False, index=True)  # wikipedia|unesco|trend
    source_ref = Column(String(200), nullable=True, index=True)
    region = Column(String(2), nullable=True, index=True)  # ISO-2, see app.collectors.region_codes

    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    # The original raw source text this item was extracted from — kept for
    # audit and re-processing, not shown to end users.
    raw_text = Column(Text, nullable=True)

    category = Column(String(20), nullable=False, index=True)  # history|archaeology|culture|humor|tech|innovation|trending|geopolitical

    recency_score = Column(Integer, nullable=True)
    popularity_score = Column(Integer, nullable=True)
    cultural_weight = Column(Integer, nullable=True)
    evergreen_value = Column(Integer, nullable=True)
    priority_score = Column(Integer, nullable=True, index=True)
    challenge_notes = Column(Text, nullable=True)
    pipeline_decision = Column(String(20), nullable=True, index=True)  # include|exclude|store_for_later

    # Fixed per-category lifecycle — see DURATION_PROFILES in
    # app/services/culturix_ingestion.py. expires_at is computed at ingest
    # time (created_at + lifespan_days) so "what's stale" is a plain query
    # rather than recomputing lifespan math on every read.
    lifespan_days = Column(Integer, nullable=True)
    refresh_frequency_days = Column(Integer, nullable=True)
    decay_rate = Column(Float, nullable=True)
    auto_archive = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
