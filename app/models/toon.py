from sqlalchemy import Column, String, DateTime, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class Toon(Base):
    """The production/posting tracker tying a CharacterVariant + ToonScript
    + (optional) ToonBackground together into one plannable clip.

    final_video_url is the one video the user has picked to post — its
    meaning is unchanged from the original manual-CapCut-paste-in design.
    raw_video_url/clip_video_urls are new: the in-house Kling Omni pipeline
    (app/services/culturetoon_video.py) now generates one multi-shot video
    (raw_video_url) and cuts 3-4 candidate clips from it (clip_video_urls);
    the user picks one of those into final_video_url the same way they used
    to paste in an externally-edited link."""
    __tablename__ = "toons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    character_variant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    script_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    background_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    final_video_url = Column(Text, nullable=True)
    status = Column(String(12), nullable=False, default="idea")  # idea|animating|ready|posted|archived|failed
    platform = Column(String(20), nullable=True)  # tiktok|instagram|youtube — free text, no FK this phase
    posted_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    raw_video_url = Column(Text, nullable=True)           # the single Kling Omni multi-shot stitched output
    clip_video_urls = Column(ARRAY(Text), nullable=True)   # 3-4 ffmpeg-cut candidates
    kling_task_id = Column(String(64), nullable=True)
    generation_error = Column(Text, nullable=True)         # mirrors ShopifyProduct.reel_error's pattern

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
