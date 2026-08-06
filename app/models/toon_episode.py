from sqlalchemy import Column, String, DateTime, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonEpisode(Base):
    """An ordered sequence of existing Toons ("parts") stitched into one
    longer story — Kling Omni caps a single generation at a short duration
    (~10-15s, see app/services/culturetoon_episode.py's own comment on this
    being unverified), so a multi-minute story is assembled from several
    separately generated Toons rather than one call. A part IS a normal
    Toon (own script/cast/background, generated via the existing unchanged
    generate_video_for_toon) — see Toon.episode_id/part_order, not a join
    table, matching this codebase's established pattern for linking an
    existing row into a new grouping concept (e.g. Persona.cluster_id).

    final_video_url is the stitched result (concatenation of every attached
    part's raw_video_url, in part_order); clip_video_urls are highlight
    clips cut from that stitched video (see culturetoon_episode.py's
    generate_episode_clips), the episode-level analogue of Toon's own
    raw_video_url -> clip_video_urls pattern."""
    __tablename__ = "toon_episodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    status = Column(String(12), nullable=False, default="draft")  # draft|stitching|ready|failed|archived
    final_video_url = Column(Text, nullable=True)
    clip_video_urls = Column(ARRAY(Text), nullable=True)
    generation_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
