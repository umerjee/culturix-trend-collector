from sqlalchemy import Column, Integer, String, BigInteger, Text, JSON, TIMESTAMP, func

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
