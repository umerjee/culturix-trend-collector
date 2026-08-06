from sqlalchemy import Column, String, DateTime, Text, ARRAY, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class Culture(Base):
    """A shared reference library entry for one culture/country — global,
    not brand-scoped (like ART_STYLES' shared dict, not like CharacterBrand's
    per-user rows), since "Chinese" or "Indian" as a culture doesn't vary
    per brand. CharacterVariant.culture_id optionally links to one of these
    for structured context in script/background generation; culture_tag
    (free text) remains the fallback for a culture not yet in this library,
    so creating a variant is never gated on the library already containing
    it. See docs/culturix-comedy-architecture.md §3.7.

    Deliberately does NOT include physical/ethnic appearance fields — that's
    handled separately by _expand_variant_visual_description's LLM call.
    This table is about social/comedy context: what's actually funny about
    this culture without leaning on demeaning generalizations, and what to
    explicitly avoid."""
    __tablename__ = "cultures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(80), nullable=False, unique=True)
    country = Column(String(80), nullable=True)
    region = Column(String(80), nullable=True)
    language = Column(String(60), nullable=True)
    cultural_patterns = Column(JSON, nullable=True)  # free-form: {"food": str, "family": str, "work": str, "transport": str, "social_norms": str}
    humor_sensitivity = Column(Text, nullable=True)  # short guidance note, e.g. "food and family jokes land well; avoid caste/religion jokes"
    common_misunderstandings = Column(ARRAY(Text), nullable=True)  # comedy material: cross-cultural mix-ups
    stereotypes_to_avoid = Column(ARRAY(Text), nullable=True)  # explicit guardrails for script/QA generation
    positive_traits = Column(ARRAY(Text), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
