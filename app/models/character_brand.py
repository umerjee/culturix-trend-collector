from sqlalchemy import Column, String, Integer, DateTime, Text, Boolean, ARRAY
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

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
