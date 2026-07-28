"""Generates a short reel for a Shopify product, animating its REAL product
photo via Kling's image-to-video mode (see app/media/video.py) rather than
a generic AI-generated video — the brand has no physical access to film
these garments themselves, so the reel has to be grounded in the actual
uploaded photo, not just a text description of what the product looks like.

A real-money, slow (up to ~6 minutes) operation, so this is always run as a
background task (see main.py's POST /api/shopify/products/{id}/generate-reel)
and tracked via its own status field rather than blocking a request.
"""
import logging

logger = logging.getLogger("culturix.shopify.reels")

_DURATION_SECONDS = 5


def _build_video_prompt(product: dict) -> str:
    title = product.get("title") or "this piece"
    product_type = (product.get("product_type") or "garment").lower()
    return (
        f"Elegant fashion product video of {title}, a {product_type}. Gentle slow camera pan "
        f"and subtle zoom, fabric moving softly as if worn, soft professional studio lighting, "
        f"clean minimal background, cinematic e-commerce fashion reel style."
    )


def generate_reel_for_product(user_id, product_id) -> None:
    """Runs synchronously within a background task — updates the product row
    in place rather than returning a value, matching app/media/service.py's
    run_generation() convention for slow media-generation background work."""
    from app.db import SessionLocal
    from app.models.shopify_store import ShopifyStore
    from app.models.shopify_product import ShopifyProduct
    from app.media.video import KlingProvider
    from app.media import storage
    from datetime import datetime
    import uuid as _uuid

    session = SessionLocal()
    product = None
    try:
        store = session.query(ShopifyStore).filter_by(user_id=_uuid.UUID(str(user_id))).first()
        if not store:
            raise ValueError("No connected Shopify store for this user")
        product = (
            session.query(ShopifyProduct)
            .filter_by(id=_uuid.UUID(str(product_id)), store_id=store.id)
            .first()
        )
        if not product:
            raise ValueError("Product not found for this store")
        image_urls = product.image_urls or []
        if not image_urls:
            raise ValueError("Product has no photo to animate")

        product.reel_status = "processing"
        product.reel_error = None
        session.commit()

        prompt = _build_video_prompt({"title": product.title, "product_type": product.product_type})
        result = KlingProvider().generate(
            prompt, duration_seconds=_DURATION_SECONDS, reference_image_url=image_urls[0]
        )

        path = f"shopify/{store.id}/{product.id}/reel.mp4"
        public_url = storage.upload(result.asset_bytes, path, result.content_type)

        product.reel_status = "done"
        product.reel_video_url = public_url
        product.reel_generated_at = datetime.utcnow()
        session.commit()
        logger.info("Reel generated for product %s: %s", product_id, public_url)
    except Exception as e:
        session.rollback()
        logger.error("Reel generation failed for product %s: %s", product_id, e)
        if product is not None:
            try:
                product.reel_status = "failed"
                product.reel_error = str(e)[:2000]
                session.commit()
            except Exception:
                session.rollback()
        else:
            raise
    finally:
        session.close()
