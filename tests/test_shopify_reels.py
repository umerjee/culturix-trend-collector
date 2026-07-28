import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid
from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.shopify_store import ShopifyStore
from app.models.shopify_product import ShopifyProduct
from app.media.base import MediaResult
from app.shopify import service as shopify_service
from app.shopify import reels as shopify_reels

_RECENT = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def shopify_db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ShopifyStore.__table__, ShopifyProduct.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _connect(mocker, user_id, domain="test-store.myshopify.com"):
    mocker.patch(
        "app.shopify.client.fetch_shop_info",
        return_value={"name": "Test Store", "currency": "USD", "domain": domain},
    )
    shopify_service.connect_store(user_id, domain, "shpat_token")


def _sync_one_product(mocker, user_id, image_urls=None):
    page = {
        "products": [
            {"shopify_product_id": "1", "title": "Kurta", "description": "d", "product_type": "Kurta",
             "tags": "", "price": "45.00", "currency": "USD", "product_url": "https://x/1",
             "image_urls": image_urls if image_urls is not None else ["https://cdn.shopify.com/kurta.jpg"],
             "created_at": _RECENT},
        ],
        "has_next_page": False,
        "end_cursor": None,
    }
    mocker.patch("app.shopify.client.fetch_products_page", return_value=page)
    shopify_service.sync_products(user_id)


class TestBuildVideoPrompt:
    def test_includes_title_and_product_type(self):
        prompt = shopify_reels._build_video_prompt({"title": "Embroidered Kurta", "product_type": "Kurta"})
        assert "Embroidered Kurta" in prompt
        assert "kurta" in prompt.lower()


class TestGenerateReelForProduct:
    def test_generates_uploads_and_persists_reel(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(mocker, user_id)
        _sync_one_product(mocker, user_id)

        mock_kling = mocker.patch("app.media.video.KlingProvider")
        mock_kling.return_value.generate.return_value = MediaResult(
            asset_bytes=b"fake-mp4", content_type="video/mp4", duration_seconds=5.0, cost_usd=0.42
        )
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://supabase/reel.mp4")

        session = shopify_db()
        product_id = session.query(ShopifyProduct).first().id
        session.close()

        shopify_reels.generate_reel_for_product(user_id, product_id)

        sent_kwargs = mock_kling.return_value.generate.call_args.kwargs
        assert sent_kwargs["reference_image_url"] == "https://cdn.shopify.com/kurta.jpg"
        mock_upload.assert_called_once()

        session = shopify_db()
        row = session.query(ShopifyProduct).filter_by(id=product_id).first()
        assert row.reel_status == "done"
        assert row.reel_video_url == "https://supabase/reel.mp4"
        assert row.reel_generated_at is not None
        session.close()

    def test_sets_status_to_processing_before_kling_call(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(mocker, user_id)
        _sync_one_product(mocker, user_id)

        seen_status = []

        def _capture_and_return(*args, **kwargs):
            session = shopify_db()
            row = session.query(ShopifyProduct).first()
            seen_status.append(row.reel_status)
            session.close()
            return MediaResult(asset_bytes=b"x", content_type="video/mp4", duration_seconds=5.0, cost_usd=0.42)

        mock_kling = mocker.patch("app.media.video.KlingProvider")
        mock_kling.return_value.generate.side_effect = _capture_and_return
        mocker.patch("app.media.storage.upload", return_value="https://supabase/reel.mp4")

        session = shopify_db()
        product_id = session.query(ShopifyProduct).first().id
        session.close()

        shopify_reels.generate_reel_for_product(user_id, product_id)

        assert seen_status == ["processing"]

    def test_no_photo_marks_failed_without_calling_kling(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(mocker, user_id)
        _sync_one_product(mocker, user_id, image_urls=[])
        mock_kling = mocker.patch("app.media.video.KlingProvider")

        session = shopify_db()
        product_id = session.query(ShopifyProduct).first().id
        session.close()

        shopify_reels.generate_reel_for_product(user_id, product_id)

        mock_kling.return_value.generate.assert_not_called()
        session = shopify_db()
        row = session.query(ShopifyProduct).filter_by(id=product_id).first()
        assert row.reel_status == "failed"
        assert "no photo" in row.reel_error.lower()
        session.close()

    def test_kling_failure_marks_status_failed_with_error(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(mocker, user_id)
        _sync_one_product(mocker, user_id)
        mock_kling = mocker.patch("app.media.video.KlingProvider")
        mock_kling.return_value.generate.side_effect = RuntimeError("Kling task failed: unsafe image")

        session = shopify_db()
        product_id = session.query(ShopifyProduct).first().id
        session.close()

        shopify_reels.generate_reel_for_product(user_id, product_id)

        session = shopify_db()
        row = session.query(ShopifyProduct).filter_by(id=product_id).first()
        assert row.reel_status == "failed"
        assert "unsafe image" in row.reel_error
        session.close()

    def test_no_store_raises(self, shopify_db):
        with pytest.raises(ValueError, match="No connected Shopify store"):
            shopify_reels.generate_reel_for_product(uuid.uuid4(), uuid.uuid4())
