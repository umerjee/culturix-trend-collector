"""Tests confirming app/main.py's social/Shopify OAuth connect+callback
routes actually use app/oauth_state.py's signing (not just that the
signing module itself works in isolation — tests/test_oauth_state.py
covers that). The vulnerability this closes: without signing, calling
.../connect?user_id=<victim> directly (skipping the Next.js proxy that
would normally resolve user_id from a verified session) let an attacker
complete their OWN OAuth consent and have it attached to the victim's
account."""
import os
import uuid

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.connected_account import ConnectedAccount
from app.oauth_state import sign, verify_and_unwrap
from app.main import social_connect, social_callback, shopify_connect, shopify_callback


@pytest.fixture(autouse=True)
def _oauth_secret(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "test-secret-value")


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ConnectedAccount.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestSocialConnectSignsState:
    def test_redirect_state_is_signed_and_unwraps_to_the_requested_identity(self, mocker):
        provider = mocker.Mock()
        provider.get_authorize_url.return_value = "https://platform.example/authorize"
        mocker.patch("app.main._get_social_provider", return_value=provider)

        user_id = str(uuid.uuid4())
        social_connect("youtube", user_id=user_id)

        signed_state = provider.get_authorize_url.call_args.kwargs["state"]
        assert signed_state != f"{user_id}::"  # not the bare, unsigned payload
        assert verify_and_unwrap(signed_state) == f"{user_id}::"


class TestSocialCallbackRejectsUnsignedOrTamperedState:
    def test_raw_unsigned_user_id_as_state_is_rejected(self, db, mocker):
        # This is exactly what an attacker would try: skip social_connect
        # entirely and hand the callback a bare user_id as `state`.
        from fastapi.responses import RedirectResponse
        victim_id = str(uuid.uuid4())

        result = social_callback("youtube", code="some-code", state=victim_id)

        assert isinstance(result, RedirectResponse)
        assert "social_error=invalid_state" in result.headers["location"]
        session = db()
        assert session.query(ConnectedAccount).count() == 0
        session.close()

    def test_tampered_signed_state_is_rejected(self, db):
        from fastapi.responses import RedirectResponse
        real_state = sign(f"{uuid.uuid4()}::")
        payload, ts, sig = real_state.rsplit(".", 2)
        tampered = f"{uuid.uuid4()}.{ts}.{sig}"  # swapped in an attacker-chosen user_id

        result = social_callback("youtube", code="some-code", state=tampered)

        assert "social_error=invalid_state" in result.headers["location"]

    def test_properly_signed_state_is_accepted(self, db, mocker):
        result_obj = mocker.Mock(
            access_token="tok", refresh_token=None, expires_in_seconds=None,
            platform_account_id="acct-1", platform_username="someone",
        )
        provider = mocker.Mock()
        provider.exchange_code.return_value = result_obj
        mocker.patch("app.main._get_social_provider", return_value=provider)
        mocker.patch("app.social.crypto.encrypt", return_value="encrypted")

        user_id = uuid.uuid4()
        signed_state = sign(f"{user_id}::")

        from fastapi.responses import RedirectResponse
        result = social_callback("youtube", code="some-code", state=signed_state)

        assert isinstance(result, RedirectResponse)
        assert "social_error" not in result.headers["location"]
        session = db()
        assert session.query(ConnectedAccount).filter_by(user_id=user_id).count() == 1
        session.close()


class TestShopifyConnectSignsState:
    def test_redirect_state_is_signed(self, mocker):
        mocker.patch("app.shopify.service.normalize_domain", side_effect=lambda d: d)
        mocker.patch("app.shopify.oauth.is_valid_shop_domain", return_value=True)
        mock_authorize = mocker.patch("app.shopify.oauth.get_authorize_url", return_value="https://shopify.example/authorize")

        user_id = str(uuid.uuid4())
        shopify_connect(user_id=user_id, shop_domain="store.myshopify.com")

        signed_state = mock_authorize.call_args.kwargs["state"]
        assert signed_state != user_id
        assert verify_and_unwrap(signed_state) == user_id


class TestShopifyCallbackRejectsUnsignedOrTamperedState:
    def test_raw_unsigned_user_id_as_state_is_rejected(self, mocker):
        mocker.patch("app.shopify.oauth.is_valid_shop_domain", return_value=True)
        mocker.patch("app.shopify.oauth.verify_hmac", return_value=True)
        mock_connect_store = mocker.patch("app.shopify.service.connect_store")
        request = mocker.Mock()
        request.query_params = {
            "shop": "store.myshopify.com", "code": "abc",
            "state": str(uuid.uuid4()),  # bare, unsigned
        }

        result = shopify_callback(request, background_tasks=mocker.Mock())

        assert "shopify_error=invalid_state" in result.headers["location"]
        mock_connect_store.assert_not_called()

    def test_properly_signed_state_is_accepted(self, mocker):
        mocker.patch("app.shopify.oauth.is_valid_shop_domain", return_value=True)
        mocker.patch("app.shopify.oauth.verify_hmac", return_value=True)
        mocker.patch("app.shopify.oauth.exchange_code", return_value="token")
        mock_connect_store = mocker.patch("app.shopify.service.connect_store")
        mocker.patch("app.shopify.service.sync_products")
        user_id = str(uuid.uuid4())
        request = mocker.Mock()
        request.query_params = {
            "shop": "store.myshopify.com", "code": "abc", "state": sign(user_id),
        }

        result = shopify_callback(request, background_tasks=mocker.Mock())

        assert "shopify_error" not in result.headers["location"]
        mock_connect_store.assert_called_once_with(user_id, "store.myshopify.com", "token")
