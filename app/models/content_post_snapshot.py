from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ContentPostSnapshot(Base):
    __tablename__ = "content_post_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_post_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    captured_at = Column(DateTime, default=datetime.utcnow)
    views = Column(Integer, nullable=True)
    likes = Column(Integer, nullable=True)
    comments = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
