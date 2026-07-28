from sqlalchemy import Column, String, DateTime, Text, Boolean, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.db import Base


class ShopifyProduct(Base):
    """One row per Shopify product, synced from the Admin GraphQL API (see
    app/shopify/client.py). A product no longer returned by a sync is marked
    is_active=False rather than deleted, matching this codebase's
    status-not-delete convention (ConnectedAccount.status, Cluster, etc.)."""
    __tablename__ = "shopify_products"
    __table_args__ = (
        UniqueConstraint("store_id", "shopify_product_id", name="uq_shopify_products_store_product"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    shopify_product_id = Column(String(64), nullable=False)  # numeric Shopify GID tail, as a string
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    product_type = Column(String(255), nullable=True)
    tags = Column(Text, nullable=True)  # comma-separated
    price = Column(String(20), nullable=True)  # kept as a string — avoids float precision on currency
    currency = Column(String(10), nullable=True)
    image_urls = Column(JSON, nullable=True)  # list[str]
    product_url = Column(String(1000), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    synced_at = Column(DateTime, default=datetime.utcnow)
