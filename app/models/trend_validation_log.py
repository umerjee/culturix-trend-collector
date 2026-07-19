from sqlalchemy import Column, String, DateTime, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class TrendValidationLog(Base):
    __tablename__ = "trend_validation_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(20), nullable=False)  # "cluster" | "idea"
    subject = Column(Text, nullable=False)  # cluster theme or idea hook, for identification
    legitimate = Column(Boolean, nullable=True)
    safe = Column(Boolean, nullable=True)
    durability = Column(String(20), nullable=True)  # "sustained" | "spike" | "unclear" | null
    status = Column(String(20), nullable=False)  # "approved" | "rejected"
    reason = Column(Text, nullable=True)
    checked_at = Column(DateTime, default=datetime.utcnow)
