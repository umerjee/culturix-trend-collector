from sqlalchemy import Column, Integer, String, BigInteger, Text, JSON, TIMESTAMP, Float, func
from sqlalchemy.orm import relationship

from app.db import Base


class Trend(Base):
    __tablename__ = "trends"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, index=True, nullable=False)
    external_id = Column(String, index=True)
    url = Column(Text)
    title = Column(Text)
    content = Column(Text)
    author = Column(String)
    likes = Column(Integer)
    comments = Column(Integer)
    shares = Column(Integer)
    views = Column(BigInteger)
    collected_at = Column(TIMESTAMP, server_default=func.now())
    posted_at = Column(TIMESTAMP)
    raw_json = Column(JSON)
    language = Column(String(10), nullable=True)
    translated_content = Column(Text, nullable=True)
    embedding = Column(JSON, nullable=True)
    cluster_id = Column(Integer, nullable=True)
    # likes / (hours_since_posted + 1) — recency-weighted growth proxy, written
    # by the Scrapy velocity pipeline (scraping/culturix_scraping/pipelines.py)
    velocity_score = Column(Float, nullable=True)

    personas = relationship("TrendPersona", back_populates="trend")
