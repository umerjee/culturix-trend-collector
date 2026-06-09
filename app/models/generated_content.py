from sqlalchemy import Column, String, DateTime, Date, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime, date
import uuid
from app.db import Base


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    generated_at = Column(DateTime, default=datetime.utcnow)
    trend_date = Column(Date, default=date.today)
    clusters = Column(JSONB, default=list)
    content_ideas = Column(JSONB, default=list)
    delivered = Column(Boolean, default=False)
