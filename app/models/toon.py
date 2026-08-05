from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class Toon(Base):
    """The production/posting tracker tying a CharacterVariant + ToonScript
    + (optional) ToonBackground together into one plannable clip. Final
    videos are produced externally (CapCut/Blender) for now — final_video_url
    is manually pasted in once the user has exported it there; there is no
    in-house rendering pipeline for this yet."""
    __tablename__ = "toons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    character_variant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    script_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    background_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    final_video_url = Column(Text, nullable=True)
    status = Column(String(12), nullable=False, default="idea")  # idea|animating|ready|posted|archived
    platform = Column(String(20), nullable=True)  # tiktok|instagram|youtube — free text, no FK this phase
    posted_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
