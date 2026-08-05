from sqlalchemy import Column, String, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ToonPost(Base):
    """Publish/track record for one Toon posted to one platform — the
    CultureToons analogue of ContentPost, kept as its own model rather than
    overloading ContentPost (which is tightly coupled to
    GeneratedContent/idea_index, neither of which a Toon has). Status
    vocabulary mirrors ContentPost's pending|tracked|failed|needs_reconnect;
    CultureToons has no stage-and-notify equivalent (Toons are generated
    on-demand, not on a daily cadence), so there's no "staged"/"fetching"
    state here — publish_toon_and_record (app/social/service.py) takes a row
    straight from pending to its terminal state in one background pass, the
    same shape ContentPost's own dormant run_auto_publish() direct-publish
    path uses."""
    __tablename__ = "toon_posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    toon_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    brand_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    platform = Column(String(20), nullable=False)
    post_url = Column(Text, nullable=True)
    platform_post_id = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending|tracked|failed|needs_reconnect
    latest_views = Column(Integer, nullable=True)
    latest_likes = Column(Integer, nullable=True)
    latest_comments = Column(Integer, nullable=True)
    latest_shares = Column(Integer, nullable=True)
    last_fetched_at = Column(DateTime, nullable=True)
    tracking_until = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True)
