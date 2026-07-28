"""Shopify store connection + product catalog sync — the ingestion layer
for the planned Shopify-linked content feature (daily reels/posts generated
from a brand's real product catalog).

Auth is OAuth (custom distribution — see app/shopify/oauth.py for why not a
public App Store listing yet): main.py's /api/shopify/connect and /callback
routes handle the authorize/exchange cycle and hand this module a real
access_token to persist. app/social/'s OAuthProvider ABC doesn't apply here
— Shopify's token flow has no refresh step and none of the publish/
fetch_post_metrics shape that ABC assumes — so this gets its own small
module instead of being forced into that shape.

One store per user for now, matching the pilot's single-store scope.
"""
import logging
from datetime import datetime
from typing import Optional
import uuid as _uuid

logger = logging.getLogger("culturix.shopify")


def normalize_domain(shop_domain: str) -> str:
    d = shop_domain.strip().lower()
    if d.startswith("https://"):
        d = d[len("https://"):]
    elif d.startswith("http://"):
        d = d[len("http://"):]
    d = d.rstrip("/")
    if not d.endswith(".myshopify.com") and "." not in d:
        d = f"{d}.myshopify.com"
    return d


def connect_store(user_id, shop_domain: str, access_token: str):
    """Validates the token/domain with a live Shopify call before persisting
    anything — a bad token should fail loudly here, not silently on the
    first sync."""
    from app.db import SessionLocal
    from app.models.shopify_store import ShopifyStore
    from app.shopify.client import fetch_shop_info
    from app.social.crypto import encrypt

    domain = normalize_domain(shop_domain)
    info = fetch_shop_info(domain, access_token)

    session = SessionLocal()
    try:
        uid = _uuid.UUID(str(user_id))
        store = session.query(ShopifyStore).filter_by(user_id=uid).first()
        if not store:
            store = ShopifyStore(user_id=uid)
            session.add(store)
        store.shop_domain = info["domain"]
        store.access_token = encrypt(access_token)
        store.shop_name = info["name"]
        store.currency = info["currency"]
        store.is_active = True
        store.connected_at = datetime.utcnow()
        store.last_sync_status = None
        store.last_sync_error = None
        session.commit()
        return {
            "shop_domain": store.shop_domain,
            "shop_name": store.shop_name,
            "currency": store.currency,
        }
    finally:
        session.close()


_SYNC_LOOKBACK_DAYS = 90


def _parse_shopify_datetime(value: Optional[str]):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def sync_products(user_id) -> dict:
    """Paginates products created in the last _SYNC_LOOKBACK_DAYS and upserts
    into shopify_products — scoped to recent products rather than the full
    catalog history, both because only-recently-added products are what
    matter for content generation, and because a large store's full catalog
    can burn through Shopify's GraphQL rate limit before pagination finishes
    (live-confirmed against a real store with a large product count).

    Products within that window no longer returned by Shopify are marked
    is_active=False rather than deleted (status-not-delete convention).
    Products outside the window are never touched by this function at all —
    not being in scope isn't the same as no longer existing, so leaving them
    alone (rather than deactivating everything not freshly re-seen) avoids
    incorrectly deactivating a store's entire older catalog on every sync."""
    from app.db import SessionLocal
    from app.models.shopify_store import ShopifyStore
    from app.models.shopify_product import ShopifyProduct
    from app.shopify.client import fetch_products_page
    from app.social.crypto import decrypt
    from datetime import timedelta

    session = SessionLocal()
    uid = _uuid.UUID(str(user_id))
    store = None
    try:
        store = session.query(ShopifyStore).filter_by(user_id=uid, is_active=True).first()
        if not store:
            raise ValueError("No connected Shopify store for this user")

        # Guard against concurrent duplicate runs — every earlier trigger
        # (OAuth callback's auto-sync, manual POST /api/shopify/sync retries)
        # started its own independent background task with nothing stopping
        # them piling up. Live-confirmed: several of these ended up running
        # at once against a large catalog, all racing each other on the same
        # upserts, which was the actual cause of unrelated reads against
        # these tables hanging — not a stuck/infinite loop in any single run.
        if store.last_sync_status == "running":
            logger.info("Shopify sync for user %s already in progress — skipping duplicate trigger", user_id)
            return {"synced": 0, "deactivated": 0, "skipped": "already running"}
        store.last_sync_status = "running"
        session.commit()

        access_token = decrypt(store.access_token)
        cutoff = datetime.utcnow() - timedelta(days=_SYNC_LOOKBACK_DAYS)
        seen_ids = set()
        cursor = None
        synced = 0
        while True:
            page = fetch_products_page(
                store.shop_domain, access_token, cursor=cursor,
                created_after=cutoff.strftime("%Y-%m-%d"),
            )
            for p in page["products"]:
                seen_ids.add(p["shopify_product_id"])
                row = (
                    session.query(ShopifyProduct)
                    .filter_by(store_id=store.id, shopify_product_id=p["shopify_product_id"])
                    .first()
                )
                if not row:
                    row = ShopifyProduct(store_id=store.id, shopify_product_id=p["shopify_product_id"])
                    session.add(row)
                row.title = p["title"]
                row.description = p["description"]
                row.product_type = p["product_type"]
                row.tags = p["tags"]
                row.product_created_at = _parse_shopify_datetime(p.get("created_at"))
                row.price = p["price"]
                row.currency = p["currency"]
                row.product_url = p["product_url"]
                row.image_urls = p["image_urls"]
                row.is_active = True
                row.synced_at = datetime.utcnow()
                synced += 1
            # Commit per page rather than once at the end — a large catalog
            # combined with throttle-retry backoff (see client.py) can make
            # one sync run for several minutes; holding a single open
            # session/connection for that whole duration was observed live
            # to starve the DB connection pool for unrelated requests (e.g.
            # a simple GET /api/shopify/store hanging while a sync was still
            # in progress). Committing here also means a mid-run failure
            # doesn't lose already-fetched pages.
            session.commit()
            if not page["has_next_page"]:
                break
            cursor = page["end_cursor"]

        stale_query = session.query(ShopifyProduct).filter(
            ShopifyProduct.store_id == store.id,
            ShopifyProduct.is_active.is_(True),
            ShopifyProduct.product_created_at >= cutoff,
        )
        if seen_ids:
            stale_query = stale_query.filter(~ShopifyProduct.shopify_product_id.in_(seen_ids))
        deactivated = 0
        for row in stale_query.all():
            row.is_active = False
            deactivated += 1

        store.last_synced_at = datetime.utcnow()
        store.last_sync_status = "ok"
        store.last_sync_error = None
        session.commit()
        logger.info("Shopify sync for user %s: %d synced, %d deactivated", user_id, synced, deactivated)
        return {"synced": synced, "deactivated": deactivated}
    except Exception as e:
        session.rollback()
        logger.error("Shopify sync failed for user %s: %s", user_id, e)
        if store is not None:
            try:
                store.last_sync_status = "error"
                store.last_sync_error = str(e)[:2000]
                session.commit()
            except Exception:
                session.rollback()
        raise
    finally:
        session.close()


def get_store(user_id) -> Optional[dict]:
    from app.db import SessionLocal
    from app.models.shopify_store import ShopifyStore
    from app.models.shopify_product import ShopifyProduct

    session = SessionLocal()
    try:
        store = session.query(ShopifyStore).filter_by(
            user_id=_uuid.UUID(str(user_id)), is_active=True
        ).first()
        if not store:
            return None
        product_count = (
            session.query(ShopifyProduct)
            .filter_by(store_id=store.id, is_active=True)
            .count()
        )
        return {
            "shop_domain": store.shop_domain,
            "shop_name": store.shop_name,
            "currency": store.currency,
            "connected_at": store.connected_at.isoformat() if store.connected_at else None,
            "last_synced_at": store.last_synced_at.isoformat() if store.last_synced_at else None,
            "last_sync_status": store.last_sync_status,
            "last_sync_error": store.last_sync_error,
            "product_count": product_count,
        }
    finally:
        session.close()


def list_products(user_id, active_only: bool = True) -> list:
    from app.db import SessionLocal
    from app.models.shopify_store import ShopifyStore
    from app.models.shopify_product import ShopifyProduct

    session = SessionLocal()
    try:
        store = session.query(ShopifyStore).filter_by(user_id=_uuid.UUID(str(user_id))).first()
        if not store:
            return []
        query = session.query(ShopifyProduct).filter_by(store_id=store.id)
        if active_only:
            query = query.filter_by(is_active=True)
        return [
            {
                "id": str(p.id),
                "shopify_product_id": p.shopify_product_id,
                "title": p.title,
                "description": p.description,
                "product_type": p.product_type,
                "tags": p.tags,
                "price": p.price,
                "currency": p.currency,
                "product_url": p.product_url,
                "image_urls": p.image_urls or [],
                "product_created_at": p.product_created_at.isoformat() if p.product_created_at else None,
                "synced_at": p.synced_at.isoformat() if p.synced_at else None,
            }
            for p in query.order_by(ShopifyProduct.title).all()
        ]
    finally:
        session.close()


def disconnect_store(user_id) -> None:
    from app.db import SessionLocal
    from app.models.shopify_store import ShopifyStore

    session = SessionLocal()
    try:
        store = session.query(ShopifyStore).filter_by(user_id=_uuid.UUID(str(user_id))).first()
        if store:
            store.is_active = False  # soft — matches ConnectedAccount's status-not-delete convention
            session.commit()
    finally:
        session.close()
