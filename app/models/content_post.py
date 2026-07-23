from sqlalchemy import Column, String, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ContentPost(Base):
    __tablename__ = "content_posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_content_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    idea_index = Column(Integer, nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    platform = Column(String(20), nullable=False)
    post_url = Column(Text, nullable=True)
    platform_post_id = Column(String(255), nullable=True)
    created_via = Column(String(10), nullable=False)  # manual|published|staged
    # pending|fetching|tracked|failed|needs_reconnect|staged — "staged" means
    # video+caption are ready and a notification has been attempted; the row
    # moves to "pending" once the user confirms they posted it themselves
    # (see /confirm-posted), then flows through the states above unchanged.
    status = Column(String(20), nullable=False, default="pending")
    latest_views = Column(Integer, nullable=True)
    latest_likes = Column(Integer, nullable=True)
    latest_comments = Column(Integer, nullable=True)
    latest_shares = Column(Integer, nullable=True)
    last_fetched_at = Column(DateTime, nullable=True)
    tracking_until = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True)
    # Pre-written caption+hashtags for the notify-to-publish flow (see
    # app/social/service.py's compile_caption_text) — persisted so the
    # landing page and push payload always show exactly what was staged.
    caption_text = Column(Text, nullable=True)
    notification_status = Column(String(10), nullable=True)  # sent|failed — NULL = not attempted
    notified_at = Column(DateTime, nullable=True)
