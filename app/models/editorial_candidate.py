from sqlalchemy import Column, String, DateTime, Integer, Float, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class EditorialCandidate(Base):
    """One trend-to-culture editorial candidate for CultureToons: a current trend in a country,
    paired with a curated historical/cultural source from that same country. Internal/admin only.

    Lifecycle (`status`): candidate -> scripted -> approved -> published, or rejected/blocked.
    `blocked` is terminal: an automatic safety exclusion or an operator's block. Safety is a gate,
    never a ranking weight, so a blocked row keeps rank_score NULL.

    The trend and source are SNAPSHOTS taken when the candidate is built. Trend rows and clusters
    are rewritten by the collectors and clustering, so a later reader must still see exactly what
    the operator saw. source_excerpt is the only text the script is allowed to state facts from
    (see app/services/editorial.py); trend text is context for the joke, never a fact source.

    Per-post platform/URL/metrics live on toon_posts (joined through toon_id) so the existing
    CultureToons analytics keep reading the same rows. See app/services/editorial.py's
    performance_rows for the learning view."""
    __tablename__ = "editorial_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Trend snapshot: trend_type is "cluster" (a persisted Cluster) or "trend" (one Trend row).
    trend_type = Column(String(10), nullable=False)
    trend_id = Column(Integer, nullable=False, index=True)
    trend_title = Column(Text, nullable=False)
    trend_summary = Column(Text, nullable=True)
    trend_platforms = Column(JSON, nullable=True)  # [str]
    trend_momentum = Column(String(10), nullable=True)  # Cluster.momentum: up|neutral|down|NULL

    region = Column(String(2), nullable=False, index=True)  # ISO-2
    continent = Column(String(20), nullable=False, index=True)

    # Source snapshot (a CuratedItem: Wikipedia / UNESCO).
    curated_item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    source_title = Column(Text, nullable=False)
    source_url = Column(Text, nullable=False)
    source_excerpt = Column(Text, nullable=False)

    # Ranking: rank_score is the weighted sum; rank_factors is [{factor, score, weight, reason}].
    rank_score = Column(Float, nullable=True, index=True)
    rank_factors = Column(JSON, nullable=True)
    rank_weights_version = Column(Integer, nullable=True)

    status = Column(String(12), nullable=False, default="candidate", index=True)

    # Safety: safety_flags are automatic screen hits (any hit = blocked, no override);
    # safety_review_flags are things a person must look at; safety_checklist is the operator's
    # signed-off answers. safety_status: pending|cleared|blocked.
    safety_status = Column(String(10), nullable=False, default="pending")
    safety_flags = Column(JSON, nullable=True)
    safety_review_flags = Column(JSON, nullable=True)
    safety_checklist = Column(JSON, nullable=True)
    safety_note = Column(Text, nullable=True)
    safety_reviewed_by = Column(String(255), nullable=True)
    safety_reviewed_at = Column(DateTime, nullable=True)

    # Script + grounding. grounding = {"grounded", "unsupported_claims", "judge_failed", "claims":
    # [{text, shot_number, source_sentence, supported}]}; grounding_status: pending|grounded|
    # unsupported|unchecked.
    brand_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    script_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    grounding = Column(JSON, nullable=True)
    grounding_status = Column(String(12), nullable=False, default="pending")
    language = Column(String(10), nullable=False, default="en")
    format = Column(String(30), nullable=True)  # see EDITORIAL_FORMATS in app/services/editorial.py

    # Set at approval. approved_script_fingerprint detects an edit to the script after approval,
    # which re-opens the grounding gate.
    toon_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    approved_script_fingerprint = Column(String(64), nullable=True)
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
