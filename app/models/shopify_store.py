from sqlalchemy import Column, String, DateTime, Text, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ShopifyStore(Base):
    """A Shopify store connected to a user via a custom-app access token
    (pasted in by the store owner from their own Shopify admin) rather than
    OAuth — see app/shopify/service.py's module docstring for why. One store
    per user for now, matching the pilot's single-multi-brand-store scope."""
    __tablename__ = "shopify_stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    shop_domain = Column(String(255), nullable=False)  # e.g. "my-store.myshopify.com"
    access_token = Column(Text, nullable=False)  # encrypted at rest — see app/social/crypto.py
    shop_name = Column(String(255), nullable=True)
    currency = Column(String(10), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    connected_at = Column(DateTime, default=datetime.utcnow)
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String(10), nullable=True)  # ok|error
    last_sync_error = Column(Text, nullable=True)
