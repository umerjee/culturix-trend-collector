from sqlalchemy import Column, String, DateTime, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class GenerationUsage(Base):
    """One row per AI-generation call across CultureToons (video, image,
    voice, Kling Element/voice registration) — the record budget enforcement
    (app/services/culturetoon_usage.py::check_budget) sums against.

    cost_usd confidence varies by provider — see culturetoon_usage.py's
    module docstring: image generation reuses whatever HybridImageProvider's
    MediaResult.cost_usd already reports (verified for Cloudflare's free
    tier, genuinely unknown/None for Qwen-Image — app/media/image.py's own
    _COST_USD is None, not fabricated here); video/voice/registration costs
    are estimated from placeholder per-unit rates pending real invoiced
    numbers. NULL cost_usd means "not yet priced," not "free" — do not treat
    NULL as 0 when reasoning about total spend."""
    __tablename__ = "generation_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    toon_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    episode_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # set for scene-level generation
    scene_id = Column(UUID(as_uuid=True), nullable=True, index=True)    # see app/models/toon_scene.py
    shot_id = Column(UUID(as_uuid=True), nullable=True, index=True)     # see app/models/toon_shot.py
    provider = Column(String(30), nullable=False)          # kling_omni|hybrid_image|elevenlabs
    model = Column(String(60), nullable=True)               # e.g. cloudflare_flux|qwen_image
    generation_type = Column(String(30), nullable=False)    # video|character_image|variant_image|
                                                              # background_image|voice_dubbing|
                                                              # element_registration|voice_registration|
                                                              # toon_video_selfhosted|lora_preview
    input_units = Column(Integer, nullable=True)             # e.g. char count for voice
    output_units = Column(Integer, nullable=True)            # e.g. duration_seconds for video (int-rounded)
    cost_usd = Column(Numeric(10, 4), nullable=True)         # NULL = not yet priced, see class docstring
    created_at = Column(DateTime, default=datetime.utcnow)
