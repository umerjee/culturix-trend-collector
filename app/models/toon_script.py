from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonScript(Base):
    """A short punchy skit script for a CultureToons brand. Optionally FK'd
    to a CharacterVariant it was written for, and optionally grounded in a
    trending Persona or Cluster via source_type/source_id — mirrors Clip's
    exact source_type/source_id pattern (app/models/clip.py): source_id is
    Integer since Persona.id/Cluster.id are Integer, not UUID. Both source
    fields are NULL for a hand-authored script.

    hook_line/dialogue/scene_direction are the original flat shape, still
    used verbatim by the manual-authoring path (POST /scripts). AI-suggested
    scripts (POST /scripts/suggest, generation_source="ai") and scheduler-
    generated auto-drafts (app.scheduler::run_culturetoon_trend_dispatch,
    generation_source="ai_auto") instead populate hook_line (as a
    human-readable summary) plus tone/shots/total_duration_seconds — the
    shot-structured shape needed to drive Kling's multi-shot video
    generation (see app/services/culturetoon_script.py's build_kling_prompt).
    dialogue/scene_direction are left NULL for both AI-suggested and
    ai_auto scripts. generation_source="ai_auto" additionally means the
    user never asked for this specific draft — it was proactively created
    from a trending Persona/Cluster on the brand's own delivery cadence
    (CharacterBrand.delivery_freq/delivery_time/delivery_day_of_week), and
    starts life at status="draft" for the user to Approve or Dismiss."""
    __tablename__ = "toon_scripts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # "Primary" speaker — kept as the single source of truth for the
    # single-character case and for backward compat. For multi-character
    # scenes, character_variant_ids below is the authoritative full cast;
    # this stays equal to character_variant_ids[0].
    character_variant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # Full cast for this script, additive alongside character_variant_id
    # rather than replacing it (this product is still beta/pilot with no
    # real customer data at stake, but an additive column is still lower
    # migration risk than a destructive rename). NULL/empty for scripts
    # created before multi-character support — callers should fall back to
    # [character_variant_id] when this is unset. Stored as TEXT[] (UUID
    # strings), not an array of the UUID type itself — matches
    # Toon.clip_video_urls' existing ARRAY(Text) convention and keeps this
    # column exercisable against SQLite in tests (conftest.py's ARRAY
    # SQLite shim round-trips via json.dumps/loads, which can't serialize
    # raw UUID objects).
    character_variant_ids = Column(ARRAY(Text), nullable=True)
    source_type = Column(String(10), nullable=True, index=True)  # persona|cluster|NULL
    source_id = Column(Integer, nullable=True, index=True)
    hook_line = Column(Text, nullable=True)
    dialogue = Column(Text, nullable=True)
    scene_direction = Column(Text, nullable=True)

    # Shot-structured script for AI-suggested/video-ready scripts.
    tone = Column(String(20), nullable=True)  # funny|dramatic|satiric|sad|wholesome|chaotic|deadpan
    # [{"shot_number": int, "duration_seconds": int, "action": str,
    #   "expression": Optional[str] (one of EXPRESSION_NAMES, free-text guidance
    #   not an FK), "dialogue": Optional[str],
    #   "speaker_variant_id": Optional[str] (which of character_variant_ids is
    #   acting/speaking in this shot — NULL defaults to the primary/first
    #   variant, so single-character scripts never need to set this)}, ...].
    # Stored structured rather than as a pre-baked "@Name ..." DSL string
    # because the element name a variant is registered under doesn't exist
    # yet at script-creation time and can change if re-registered — the DSL
    # is rebuilt on demand from this (see build_kling_prompt).
    shots = Column(JSON, nullable=True)
    total_duration_seconds = Column(Integer, nullable=True)

    # The background generated FOR this script's scene (see
    # POST /scripts/{id}/generate-background) — a script's setting drives
    # its background, not the other way around, so a Toon built from this
    # script defaults to inheriting it rather than picking one blind.
    background_id = Column(UUID(as_uuid=True), nullable=True)

    generation_source = Column(String(10), nullable=False, default="manual")  # manual|ai|ai_auto
    status = Column(String(12), nullable=False, default="draft")  # draft|approved|archived
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
