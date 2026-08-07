from sqlalchemy import Column, String, DateTime, Text, Boolean, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonBackground(Base):
    """A reusable background/location belonging to a CharacterBrand (not to
    any one Character — locations are meant to be rotated across
    characters, per the brand's own scaling strategy).

    "Locations" per docs/culturix-character-studio-upgrade.md §4 Phase 3 —
    kept as the same ToonBackground table/model (not renamed) to avoid a
    disruptive rename of an already-live entity; the evolution is additive
    fields plus a UI relabel to "Locations", not a new entity."""
    __tablename__ = "toon_backgrounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    image_url = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)  # comma-separated, matches ShopifyProduct.tags
    # The scene description this background was generated from (usually a
    # script's scene_direction/shots — see generate_script_background in
    # app/routers/culturetoons.py). NULL for manually-uploaded backgrounds.
    description = Column(Text, nullable=True)
    country = Column(String(100), nullable=True)
    visual_style = Column(String(30), nullable=True)  # one of ART_STYLES' keys, validated at the route
    # Additional canonical angles/rooms of this same location, beyond the
    # primary image_url (e.g. a second reference for "kitchen corner" of
    # the same house) — plain array rather than a child table since these
    # carry no per-image metadata beyond the URL itself, same pattern as
    # Toon.previous_video_urls elsewhere in this schema.
    reference_image_urls = Column(ARRAY(Text), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
