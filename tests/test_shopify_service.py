import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.shopify_store import ShopifyStore
from app.models.shopify_product import ShopifyProduct
from app.social.crypto import decrypt
from app.shopify import service as shopify_service


@pytest.fixture
def shopify_db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ShopifyStore.__table__, ShopifyProduct.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestConnectStore:
    def test_validates_before_persisting_and_encrypts_token(self, shopify_db, mocker):
        mocker.patch(
            "app.shopify.client.fetch_shop_info",
            return_value={"name": "Test Store", "currency": "PKR", "domain": "test-store.myshopify.com"},
        )
        user_id = uuid.uuid4()

        result = shopify_service.connect_store(user_id, "test-store.myshopify.com", "shpat_realtoken")

        assert result == {"shop_domain": "test-store.myshopify.com", "shop_name": "Test Store", "currency": "PKR"}

        session = shopify_db()
        store = session.query(ShopifyStore).filter_by(user_id=user_id).first()
        assert store is not None
        assert store.access_token != "shpat_realtoken"  # stored encrypted, not plaintext
        assert decrypt(store.access_token) == "shpat_realtoken"
        session.close()

    def test_invalid_token_raises_and_persists_nothing(self, shopify_db, mocker):
        mocker.patch("app.shopify.client.fetch_shop_info", side_effect=RuntimeError("Invalid API key"))
        user_id = uuid.uuid4()

        with pytest.raises(RuntimeError, match="Invalid API key"):
            shopify_service.connect_store(user_id, "test-store.myshopify.com", "bad-token")

        session = shopify_db()
        assert session.query(ShopifyStore).filter_by(user_id=user_id).first() is None
        session.close()

    def test_reconnecting_updates_existing_row_not_a_duplicate(self, shopify_db, mocker):
        mocker.patch(
            "app.shopify.client.fetch_shop_info",
            return_value={"name": "Test Store", "currency": "PKR", "domain": "test-store.myshopify.com"},
        )
        user_id = uuid.uuid4()
        shopify_service.connect_store(user_id, "test-store.myshopify.com", "shpat_first")
        shopify_service.connect_store(user_id, "test-store.myshopify.com", "shpat_second")

        session = shopify_db()
        rows = session.query(ShopifyStore).filter_by(user_id=user_id).all()
        assert len(rows) == 1
        assert decrypt(rows[0].access_token) == "shpat_second"
        session.close()


def _connect(shopify_db, mocker, user_id, domain="test-store.myshopify.com"):
    mocker.patch(
        "app.shopify.client.fetch_shop_info",
        return_value={"name": "Test Store", "currency": "USD", "domain": domain},
    )
    shopify_service.connect_store(user_id, domain, "shpat_token")


class TestSyncProducts:
    def test_upserts_products_and_paginates(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(shopify_db, mocker, user_id)

        page1 = {
            "products": [
                {"shopify_product_id": "1", "title": "Kurta", "description": "d", "product_type": "Kurta",
                 "tags": "eid", "price": "45.00", "currency": "USD", "product_url": "https://x/1",
                 "image_urls": ["https://x/img1.jpg"]},
            ],
            "has_next_page": True,
            "end_cursor": "cursor1",
        }
        page2 = {
            "products": [
                {"shopify_product_id": "2", "title": "Shalwar Kameez", "description": "d2", "product_type": "SK",
                 "tags": "new", "price": "60.00", "currency": "USD", "product_url": "https://x/2",
                 "image_urls": ["https://x/img2.jpg"]},
            ],
            "has_next_page": False,
            "end_cursor": None,
        }
        mocker.patch("app.shopify.client.fetch_products_page", side_effect=[page1, page2])

        result = shopify_service.sync_products(user_id)

        assert result == {"synced": 2, "deactivated": 0}
        session = shopify_db()
        products = session.query(ShopifyProduct).order_by(ShopifyProduct.shopify_product_id).all()
        assert [p.title for p in products] == ["Kurta", "Shalwar Kameez"]
        assert all(p.is_active for p in products)
        session.close()

    def test_rerunning_sync_updates_existing_row_not_a_duplicate(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(shopify_db, mocker, user_id)

        page = {
            "products": [
                {"shopify_product_id": "1", "title": "Kurta", "description": "d", "product_type": "Kurta",
                 "tags": "eid", "price": "45.00", "currency": "USD", "product_url": "https://x/1",
                 "image_urls": ["https://x/img1.jpg"]},
            ],
            "has_next_page": False,
            "end_cursor": None,
        }
        updated_page = {
            "products": [
                {**page["products"][0], "title": "Kurta (Updated Title)", "price": "50.00"},
            ],
            "has_next_page": False,
            "end_cursor": None,
        }
        mocker.patch("app.shopify.client.fetch_products_page", side_effect=[page, updated_page])

        shopify_service.sync_products(user_id)
        shopify_service.sync_products(user_id)

        session = shopify_db()
        products = session.query(ShopifyProduct).filter_by(shopify_product_id="1").all()
        assert len(products) == 1
        assert products[0].title == "Kurta (Updated Title)"
        assert products[0].price == "50.00"
        session.close()

    def test_products_missing_from_a_later_sync_are_deactivated_not_deleted(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(shopify_db, mocker, user_id)

        first_sync = {
            "products": [
                {"shopify_product_id": "1", "title": "Kurta", "description": "d", "product_type": "Kurta",
                 "tags": "", "price": "45.00", "currency": "USD", "product_url": "https://x/1", "image_urls": []},
                {"shopify_product_id": "2", "title": "Shalwar", "description": "d", "product_type": "SK",
                 "tags": "", "price": "60.00", "currency": "USD", "product_url": "https://x/2", "image_urls": []},
            ],
            "has_next_page": False,
            "end_cursor": None,
        }
        second_sync = {
            "products": [first_sync["products"][0]],  # product "2" no longer returned
            "has_next_page": False,
            "end_cursor": None,
        }
        mocker.patch("app.shopify.client.fetch_products_page", side_effect=[first_sync, second_sync])

        shopify_service.sync_products(user_id)
        result = shopify_service.sync_products(user_id)

        assert result == {"synced": 1, "deactivated": 1}
        session = shopify_db()
        row2 = session.query(ShopifyProduct).filter_by(shopify_product_id="2").first()
        assert row2.is_active is False
        row1 = session.query(ShopifyProduct).filter_by(shopify_product_id="1").first()
        assert row1.is_active is True
        session.close()

    def test_no_connected_store_raises(self, shopify_db):
        with pytest.raises(ValueError, match="No connected Shopify store"):
            shopify_service.sync_products(uuid.uuid4())

    def test_failed_sync_records_error_on_store(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(shopify_db, mocker, user_id)
        mocker.patch("app.shopify.client.fetch_products_page", side_effect=RuntimeError("rate limited"))

        with pytest.raises(RuntimeError, match="rate limited"):
            shopify_service.sync_products(user_id)

        session = shopify_db()
        store = session.query(ShopifyStore).filter_by(user_id=user_id).first()
        assert store.last_sync_status == "error"
        assert "rate limited" in store.last_sync_error
        session.close()


class TestGetStoreAndListProducts:
    def test_get_store_returns_none_when_not_connected(self, shopify_db):
        assert shopify_service.get_store(uuid.uuid4()) is None

    def test_get_store_reports_product_count(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(shopify_db, mocker, user_id)
        page = {
            "products": [
                {"shopify_product_id": "1", "title": "Kurta", "description": "d", "product_type": "Kurta",
                 "tags": "", "price": "45.00", "currency": "USD", "product_url": "https://x/1", "image_urls": []},
            ],
            "has_next_page": False,
            "end_cursor": None,
        }
        mocker.patch("app.shopify.client.fetch_products_page", return_value=page)
        shopify_service.sync_products(user_id)

        store = shopify_service.get_store(user_id)
        assert store["product_count"] == 1
        assert store["last_sync_status"] == "ok"

    def test_list_products_excludes_inactive_by_default(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(shopify_db, mocker, user_id)
        first_sync = {
            "products": [
                {"shopify_product_id": "1", "title": "Kurta", "description": "d", "product_type": "Kurta",
                 "tags": "", "price": "45.00", "currency": "USD", "product_url": "https://x/1", "image_urls": []},
                {"shopify_product_id": "2", "title": "Shalwar", "description": "d", "product_type": "SK",
                 "tags": "", "price": "60.00", "currency": "USD", "product_url": "https://x/2", "image_urls": []},
            ],
            "has_next_page": False,
            "end_cursor": None,
        }
        second_sync = {"products": [first_sync["products"][0]], "has_next_page": False, "end_cursor": None}
        mocker.patch("app.shopify.client.fetch_products_page", side_effect=[first_sync, second_sync])
        shopify_service.sync_products(user_id)
        shopify_service.sync_products(user_id)

        active = shopify_service.list_products(user_id)
        assert [p["title"] for p in active] == ["Kurta"]

        everything = shopify_service.list_products(user_id, active_only=False)
        assert len(everything) == 2


class TestDisconnectStore:
    def test_disconnect_soft_deactivates_not_deletes(self, shopify_db, mocker):
        user_id = uuid.uuid4()
        _connect(shopify_db, mocker, user_id)

        shopify_service.disconnect_store(user_id)

        session = shopify_db()
        store = session.query(ShopifyStore).filter_by(user_id=user_id).first()
        assert store is not None
        assert store.is_active is False
        session.close()
        assert shopify_service.get_store(user_id) is None
