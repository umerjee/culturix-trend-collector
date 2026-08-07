from sqlalchemy import Column, Integer, String, DateTime, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonShot(Base):
    """A single 1-5s camera setup within a ToonScene — the cinematic
    production unit beneath Scene, per docs/culturix-cinematic-shots.md:
    Episode -> Scenes -> Shots -> Video Clips -> Assembly -> Final Toon.
    A Scene can still generate directly as one clip (the pre-existing
    single-shot path, app/services/culturetoon_scene.py::generate_scene_video,
    unchanged) OR decompose into several of these for genuine multi-shot
    coverage (establishing, entrance, reaction, close-up, punchline, etc.)
    instead of every scene being two characters standing and talking.

    character_variant_ids is a list of REFERENCES (CharacterVariant ids),
    never duplicated character data — identity, personality, and canonical
    reference images are always resolved live from the persistent
    Character/CharacterVariant records at generation time, per the "do not
    duplicate character identity inside Shot" requirement. Same reasoning
    for background_id (a Location/ToonBackground reference) — inherits the
    parent Scene's background_id when unset, never stores location data
    itself.

    generation_status/kling_task_id/generation_error/generation_attempts/
    previous_asset_ids mirror ToonScene's established generation-lifecycle
    fields exactly (see that model's docstring) — added beyond the spec's
    literal field list for the same reason every other generatable entity
    in this schema has them: a shot needs a way to poll/report Kling
    progress and preserve regeneration history, not just a final result."""
    __tablename__ = "toon_shots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scene_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    shot_number = Column(Integer, nullable=False)

    # ── narrative / cinematography ──────────────────────────────────────
    shot_type = Column(String(20), nullable=False, default="medium")  # see SHOT_TYPES
    duration_seconds = Column(Integer, nullable=False, default=3)  # 1-5s, see MIN/MAX_SHOT_DURATION_SECONDS
    character_variant_ids = Column(ARRAY(Text), nullable=True)  # references only, see class docstring
    background_id = Column(UUID(as_uuid=True), nullable=True)  # inherits scene's if unset
    action = Column(Text, nullable=True)
    emotion = Column(String(20), nullable=True)  # one of EXPRESSION_NAMES, same vocabulary as Scene/Script shots
    dialogue = Column(Text, nullable=True)
    comedic_beat = Column(String(20), nullable=True)  # see COMEDIC_BEATS

    # ── camera ───────────────────────────────────────────────────────────
    camera_framing = Column(Text, nullable=True)  # free text refinement beyond shot_type, e.g. "character left third"
    camera_angle = Column(Text, nullable=True)  # e.g. "low angle", "eye level" — no fixed enum, too open-ended
    camera_movement = Column(String(20), nullable=True)  # see CAMERA_MOVEMENTS
    lens = Column(Text, nullable=True)  # e.g. "35mm wide", "85mm portrait compression"
    composition = Column(Text, nullable=True)  # e.g. "rule of thirds, negative space right"
    lighting = Column(Text, nullable=True)  # e.g. "warm golden-hour side light"

    # ── generation ───────────────────────────────────────────────────────
    visual_prompt = Column(Text, nullable=True)  # the assembled Kling prompt text for this shot's visuals
    motion_prompt = Column(Text, nullable=True)  # movement/action description fed to Kling separately from visual_prompt
    audio_notes = Column(Text, nullable=True)  # dialogue|silence|ambient|sfx|music|reaction — free text for now, see docs
    # URLs actually resolved and sent to the provider for this shot's most
    # recent generation attempt (character + location reference images) —
    # resolved dynamically every call, snapshotted here for audit/debugging,
    # not a source of truth (the live Character/CharacterVariant/
    # ToonBackground records are).
    reference_assets = Column(ARRAY(Text), nullable=True)
    provider = Column(String(30), nullable=True)  # e.g. kling_omni
    model = Column(String(60), nullable=True)

    generation_status = Column(String(12), nullable=False, default="idea")  # idea|generating|ready|failed
    generation_attempts = Column(Integer, nullable=False, default=0)
    generated_asset_id = Column(Text, nullable=True)  # the resulting clip's video_url
    previous_asset_ids = Column(ARRAY(Text), nullable=True)  # regeneration history, same reasoning as ToonScene.previous_video_urls
    kling_task_id = Column(String(64), nullable=True)
    generation_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


SHOT_TYPES = [
    "establishing", "wide", "full", "medium", "medium_closeup", "closeup", "extreme_closeup",
    "over_shoulder", "two_shot", "pov", "insert", "reaction", "reveal",
]

CAMERA_MOVEMENTS = [
    "static", "push_in", "pull_out", "pan_left", "pan_right", "tilt",
    "tracking", "dolly", "orbit", "crane", "handheld", "whip_pan",
]

COMEDIC_BEATS = [
    "setup", "exposition", "anticipation", "escalation", "reaction",
    "misdirection", "reveal", "punchline", "aftermath",
]

MIN_SHOT_DURATION_SECONDS = 1
MAX_SHOT_DURATION_SECONDS = 5
