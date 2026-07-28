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
    # Shopify's own creation timestamp for the product — distinct from
    # synced_at below. Used to scope sync's stale-deactivation logic (see
    # service.py) to only the products actually within the sync's lookback
    # window, since sync_products() only fetches recently-created products.
    product_created_at = Column(DateTime, nullable=True)
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

    # AI-generated post idea for this product (see app/shopify/content_ideas.py)
    # — one proposed post per product, matching the digest's "one card per
    # product" shape. Regenerating overwrites these rather than versioning;
    # nothing here needs history the way trend ideas do.
    idea_hook = Column(Text, nullable=True)
    idea_caption = Column(Text, nullable=True)
    idea_cta = Column(String(255), nullable=True)
    idea_hashtags = Column(Text, nullable=True)
    idea_platform = Column(String(50), nullable=True)
    idea_generated_at = Column(DateTime, nullable=True)

    # AI-generated reel (Kling image-to-video, grounded in this product's own
    # photo — see app/shopify/reels.py) — a slow, real-cost operation, so
    # tracked as its own async status rather than folded into idea_* above.
    reel_status = Column(String(12), nullable=True)  # processing|done|failed
    reel_video_url = Column(Text, nullable=True)
    reel_error = Column(Text, nullable=True)
    reel_generated_at = Column(DateTime, nullable=True)
