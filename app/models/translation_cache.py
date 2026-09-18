from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.db import Base


class TranslationCache(Base):
    """A translation already paid for (see app/translation). Keyed by the
    SHA-256 of the exact source text, the target language and the engine, so a
    re-view of the same digest, brief or post costs nothing and the free Google
    endpoint (which rate-limits within a handful of calls) is barely touched.

    The source text itself is deliberately not stored: it already lives in the
    row it came from, and only its hash is needed to find this translation.
    Failures are never cached."""
    __tablename__ = "translation_cache"
    __table_args__ = (UniqueConstraint("text_hash", "target_lang", "engine", name="uq_translation_cache_key"),)

    id = Column(Integer, primary_key=True, index=True)
    text_hash = Column(String(64), nullable=False, index=True)
    target_lang = Column(String(8), nullable=False)
    engine = Column(String(16), nullable=False)
    translated_text = Column(Text, nullable=False)
    source_lang = Column(String(8), nullable=True)
    source_chars = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
