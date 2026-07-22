from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    # NULL content_profile_id = legacy/unbound, user-wide account (Postgres treats
    # NULL as distinct under a unique constraint, so these never collide with
    # profile-bound rows below — no backfill needed when this column was added).
    __table_args__ = (UniqueConstraint("content_profile_id", "platform", name="uq_connected_accounts_profile_platform"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # Which ContentProfile (niche) this connected account is dedicated to — a
    # user's own "avatar account" for that niche. NULL means legacy/shared
    # across all of the user's profiles (see app/social/service.py's fallback).
    content_profile_id = Column(UUID(as_uuid=True), nullable=True, index=True)
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
    # Explicit "does this connection actually work" probe, distinct from
    # `status` (which only reflects OAuth token lifecycle) — see
    # app/social/service.py's test_connection(). NULL = never tested.
    last_tested_at = Column(DateTime, nullable=True)
    last_test_status = Column(String(10), nullable=True)  # ok|error
    last_test_error = Column(Text, nullable=True)
