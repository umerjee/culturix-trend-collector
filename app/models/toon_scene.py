from sqlalchemy import Column, String, DateTime, Text, Integer, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonScene(Base):
    """One independently-generated beat within a ToonEpisode — the fine-
    grained production unit this spec asked for, reopening a decision made
    two turns earlier in the same conversation to keep one-shot generation
    (see docs/culturix-character-studio-upgrade.md §3). Deliberately scoped
    to ToonEpisode, not to a standalone Toon — a Scene has no meaning
    outside the episode it belongs to, unlike a Toon (which stays a normal
    standalone row even after being detached from an episode as a "part").
    The pre-existing Toon-parts stitching path (Toon.episode_id/part_order,
    app/services/culturetoon_episode.py::stitch_episode) is UNCHANGED and
    still the right choice for "chain a few already-finished standalone
    Toons into a longer story" — Scenes are for "produce this episode's
    story scene-by-scene from scratch, with per-scene regeneration."

    Each Scene gets its own Kling Omni call (app/services/
    culturetoon_scene.py::generate_scene_video) producing its own short
    clip; app/services/culturetoon_episode.py::assemble_episode_from_scenes
    ffmpeg-concatenates every "ready" scene's video_url, in scene_number
    order, into the episode's final_video_url. Regenerating one scene never
    touches any other scene's video_url — the whole point of this entity
    existing.

    Hard-deleted (DELETE /scenes/{id}), not soft-deleted via is_active like
    most other CultureToons entities — a Scene isn't a reusable resource
    (unlike a Background or a Character), it's disposable episode-authoring
    scaffolding."""
    __tablename__ = "toon_scenes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    scene_number = Column(Integer, nullable=False)
    # Cast for this specific scene — a scene can feature a subset of the
    # episode's overall cast (e.g. a two-hander scene within a 3-character
    # episode). Empty/null means the scene has no cast set yet.
    character_variant_ids = Column(ARRAY(Text), nullable=True)
    background_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(Text, nullable=True)
    dialogue = Column(Text, nullable=True)
    expression = Column(String(20), nullable=True)
    camera_direction = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=False, default=4)

    status = Column(String(12), nullable=False, default="idea")  # idea|generating|ready|failed
    video_url = Column(Text, nullable=True)
    previous_video_urls = Column(ARRAY(Text), nullable=True)  # same regen-history pattern as Toon
    kling_task_id = Column(String(64), nullable=True)
    generation_error = Column(Text, nullable=True)
    generation_attempts = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
