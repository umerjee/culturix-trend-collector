from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ARRAY, Numeric, JSON
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class CharacterBrand(Base):
    """One row per themed "toon account" (e.g. "Funny Clips", "Baby Videos",
    "Tech Updates") — many per user, mirroring ContentProfile's pattern (a
    user manages several of these centrally). Owns Characters, Backgrounds,
    Scripts, and Toons."""
    __tablename__ = "character_brands"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(120), nullable=False, default="My CultureToons Brand")
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Posting cadence — schema only, mirrors ContentProfile's fields exactly.
    # No automation loop reads these yet; this just gives each brand a place
    # to declare its own cadence independent of every other brand a user runs.
    target_platforms = Column(ARRAY(Text), default=list)
    delivery_freq = Column(String(10), nullable=False, default="daily")
    delivery_time = Column(Text, nullable=False, default="07:00")
    delivery_day_of_week = Column(Integer, nullable=False, default=0)

    # Optional per-brand ElevenLabs credential — lets a user opt a brand's
    # characters into ElevenLabs voice generation instead of Kling's native
    # voice/lip-sync (unverified as of this writing — see
    # app/media/elevenlabs_voice.py). Encrypted via app/social/crypto.py's
    # existing helper, same pattern as ConnectedAccount's OAuth tokens.
    elevenlabs_api_key_encrypted = Column(Text, nullable=True)

    # Free-text description of what trend-based scripts should be about for
    # this specific toon account (e.g. "family comedy, workplace
    # awkwardness, cultural misunderstandings") — without this, the Scripts
    # tab's "Suggest a script from a trend" picker showed the same
    # unfiltered global trend feed to every brand regardless of what it
    # actually posts. NULL means "no preference set" — falls back to the
    # old unfiltered behavior, not an empty result. See
    # app/services/culturetoon_trend_relevance.py.
    trend_interests = Column(Text, nullable=True)
    # Cached Voyage.ai embedding of trend_interests (list[float] as JSON) —
    # recomputed only when trend_interests changes (see update_brand),
    # never on every request; Voyage's free tier is 3 req/min, so this
    # can't be recomputed live on each Scripts-tab load.
    trend_interests_embedding = Column(JSON, nullable=True)

    # Spend caps enforced by app/services/culturetoon_usage.py::check_budget
    # against generation_usage rows. NULL means no cap — budgets are opt-in
    # per brand, not a default limit. See
    # docs/culturix-comedy-architecture.md §3.9.
    daily_budget = Column(Numeric(10, 2), nullable=True)
    monthly_budget = Column(Numeric(10, 2), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
