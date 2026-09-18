from sqlalchemy import Column, String, DateTime, Text, ARRAY, Integer, JSON, Boolean
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
    # Nullable: a World Feature (is_world_content=True) has no character at
    # all, or at most an optional regional host — see ToonScript's own
    # character_variant_id docstring for the same nullability rationale.
    character_variant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
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
    # QA — run automatically right after a successful generation (see
    # app/services/culturetoon_qa.py). Deliberately NOT a new Toon.status
    # value (no "qa" state inserted into idea|animating|ready|posted|
    # archived|failed) — the existing status flow stays exactly as tested;
    # QA is additive metadata layered on top of "ready", not a gate a toon
    # must pass through. publish_recommended is a soft signal the frontend
    # uses to warn before publishing, never a hard block enforced
    # server-side — a human always makes the final call. NULL means QA
    # hasn't run yet (e.g. a toon generated before this feature existed).
    qa_results = Column(JSON, nullable=True)
    publish_recommended = Column(Boolean, nullable=True)
    kling_task_id = Column(String(64), nullable=True)
    generation_error = Column(Text, nullable=True)         # mirrors ShopifyProduct.reel_error's pattern
    # Which video path actually generated this Toon — "kling_omni" (the
    # default, existing manual "Generate video" flow) or "self_hosted" (the
    # RunPod+ComfyUI+LTX-2 scheduled batch path, see
    # app/services/culturetoon_selfhosted_batch.py). NULL for toons
    # generated before this column existed. Purely for cost/debug
    # attribution — does not change how the toon is displayed/played.
    video_provider = Column(String(20), nullable=True)

    # World Features — subject-centric public content (a place/phenomenon/
    # species is the star, character is optional), distinct from ordinary
    # character-driven Toons. is_world_content is the single flag the public
    # /api/world/* routes filter on; the rest mirror ToonScript's own
    # subject_* columns so a Toon can be queried/displayed without a join
    # back to its script. See app/services/culturetoon_script.py::
    # generate_world_script and app/routers/world.py.
    is_world_content = Column(Boolean, nullable=False, default=False)
    subject_region = Column(String(2), nullable=True, index=True)
    subject_text = Column(Text, nullable=True)
    subject_category = Column(String(30), nullable=True, index=True)
    # Historical era tagging — separate from the real, scraped Trend data
    # the World map's "recent" time-cursor zone scrubs through (nothing in
    # `trends` predates June 2026). era_label is free text ("French
    # Revolution"), era_year a representative year for sorting/filtering
    # (e.g. 1789) — see app/routers/world.py's era_year_min/max filtering
    # and scripts/generate_world_feature.py's --era-label/--era-year.
    era_label = Column(Text, nullable=True)
    era_year = Column(Integer, nullable=True, index=True)
    # Provenance — the CuratedItem (real Wikipedia/UNESCO source) this World
    # Feature was produced from. Powers duplicate-draft protection and the
    # public source attribution; NULL for hand-made World Features.
    curated_item_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
