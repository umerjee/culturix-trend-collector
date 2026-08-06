from sqlalchemy import Column, String, DateTime, Text, ARRAY, Integer
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class Toon(Base):
    """The production/posting tracker tying a CharacterVariant + ToonScript
    + (optional) ToonBackground together into one plannable clip.

    final_video_url is the one video the user has picked to post — its
    meaning is unchanged from the original manual-CapCut-paste-in design.
    raw_video_url is new: the in-house Kling Omni pipeline
    (app/services/culturetoon_video.py) generates one multi-shot video and
    uploads it as raw_video_url, auto-promoting the same URL into
    final_video_url — no candidate-clip picking step, one persistent video
    per generation (still manually overridable, same as the old
    externally-edited-link paste-in). clip_video_urls is a legacy column:
    an earlier version of the pipeline cut 3-4 overlapping candidate clips
    into it, which is no longer done for a single Toon (still populated by
    the Episode-level highlight-clips step — see
    app/services/culturetoon_episode.py::generate_episode_clips, which cuts
    clips from a stitched 60-180s episode, not a single <=15s Toon).

    episode_id/part_order: NULL for a normal standalone Toon. When set, this
    Toon is one "part" of a ToonEpisode (app/models/toon_episode.py) — a
    longer story assembled by stitching several parts' raw_video_url
    together in part_order. See app/services/culturetoon_episode.py."""
    __tablename__ = "toons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    episode_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    part_order = Column(Integer, nullable=True)
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
    # Regenerating used to silently overwrite raw_video_url/final_video_url
    # with no way back to what was there before (confirmed live: a user
    # regenerated to fix one issue and lost an otherwise-good previous take
    # entirely). generate_video_for_toon pushes the pre-regeneration
    # final_video_url onto this list right before overwriting it, oldest
    # first — never trimmed/pruned, since a handful of stored video URLs is
    # negligible next to the storage cost of the videos themselves.
    previous_video_urls = Column(ARRAY(Text), nullable=True)
    kling_task_id = Column(String(64), nullable=True)
    generation_error = Column(Text, nullable=True)         # mirrors ShopifyProduct.reel_error's pattern

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
