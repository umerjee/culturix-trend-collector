from sqlalchemy import Column, String, DateTime, Integer, Text, Numeric
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class Clip(Base):
    """One row per generated short-form vertical clip (script + voiceover +
    static image w/ pan-zoom + burned-in captions), sourced from either a
    Persona or a Cluster. UUID pk to match GeneratedMedia's convention for
    generated-asset tables; source_id is Integer (not UUID) because both
    Persona.id and Cluster.id are Integer primary keys."""
    __tablename__ = "clips"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = Column(String(10), nullable=False, index=True)  # persona|cluster
    source_id = Column(Integer, nullable=False, index=True)
    script_text = Column(Text, nullable=True)
    audio_path = Column(Text, nullable=True)
    image_path = Column(Text, nullable=True)
    video_path = Column(Text, nullable=True)
    duration_seconds = Column(Numeric, nullable=True)
    status = Column(String(12), nullable=False, default="pending")  # pending|processing|complete|failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
