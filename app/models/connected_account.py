from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("user_id", "platform", name="uq_connected_accounts_user_platform"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    platform = Column(String(20), nullable=False)  # youtube|twitter|tiktok|instagram
    platform_account_id = Column(String(255), nullable=True)
    platform_username = Column(String(255), nullable=True)
    access_token = Column(Text, nullable=False)   # encrypted at rest — see app/social/crypto.py
    refresh_token = Column(Text, nullable=True)   # encrypted at rest
    token_expires_at = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active|expired|revoked|error
    connected_at = Column(DateTime, default=datetime.utcnow)
    last_refreshed_at = Column(DateTime, nullable=True)
