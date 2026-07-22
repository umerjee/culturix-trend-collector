import asyncio

import pytest
from fastapi import HTTPException

from app.main import (
    billing_create_checkout_session,
    billing_create_portal_session,
    billing_webhook,
)


class TestBillingCreateCheckoutSession:
    def test_missing_user_id_or_email_returns_400(self):
        with pytest.raises(HTTPException) as exc:
            billing_create_checkout_session({"email": "a@b.com"})
        assert exc.value.status_code == 400

    def test_unconfigured_stripe_returns_503_not_a_crash(self, monkeypatch):
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        monkeypatch.delenv("STRIPE_PRICE_ID_PRO", raising=False)
        with pytest.raises(HTTPException) as exc:
            billing_create_checkout_session({"user_id": "u1", "email": "a@b.com"})
        assert exc.value.status_code == 503

    def test_success_returns_checkout_url(self, monkeypatch, mocker):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_x")
        mocker.patch("app.billing.create_checkout_session", return_value="https://checkout.stripe.com/session123")

        result = billing_create_checkout_session({"user_id": "u1", "email": "a@b.com"})

        assert result == {"url": "https://checkout.stripe.com/session123"}

    def test_stripe_error_becomes_500_with_message_not_a_raw_crash(self, monkeypatch, mocker):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_x")
        mocker.patch("app.billing.create_checkout_session", side_effect=RuntimeError("stripe is down"))

        with pytest.raises(HTTPException) as exc:
            billing_create_checkout_session({"user_id": "u1", "email": "a@b.com"})
        assert exc.value.status_code == 500
        assert "stripe is down" in exc.value.detail


class TestBillingCreatePortalSession:
    def test_missing_user_id_returns_400(self):
        with pytest.raises(HTTPException) as exc:
            billing_create_portal_session({})
        assert exc.value.status_code == 400

    def test_unconfigured_stripe_returns_503(self, monkeypatch):
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        with pytest.raises(HTTPException) as exc:
            billing_create_portal_session({"user_id": "u1"})
        assert exc.value.status_code == 503

    def test_success_returns_portal_url(self, monkeypatch, mocker):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        mocker.patch("app.billing.create_portal_session", return_value="https://billing.stripe.com/portal123")

        result = billing_create_portal_session({"user_id": "u1"})

        assert result == {"url": "https://billing.stripe.com/portal123"}

    def test_value_error_becomes_403_not_500(self, monkeypatch, mocker):
        # e.g. user has no stripe_customer_id yet — a "you're not eligible"
        # case, not a server error.
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        mocker.patch("app.billing.create_portal_session", side_effect=ValueError("no customer on file"))

        with pytest.raises(HTTPException) as exc:
            billing_create_portal_session({"user_id": "u1"})
        assert exc.value.status_code == 403


def _fake_request(mocker, body: bytes = b"{}", sig: str = "test-sig"):
    """No pytest-asyncio in this project — every test below wraps the async
    route in asyncio.run() from a plain sync test function instead of
    depending on a new test-only package."""
    request = mocker.Mock()
    request.body = mocker.AsyncMock(return_value=body)
    request.headers = {"stripe-signature": sig}
    return request


class TestBillingWebhook:
    def test_unconfigured_webhook_secret_returns_503(self, monkeypatch, mocker):
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        request = _fake_request(mocker)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(billing_webhook(request))
        assert exc.value.status_code == 503

    def test_success_returns_ok_status(self, monkeypatch, mocker):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
        mocker.patch("app.billing.handle_webhook_event", return_value={"event": "checkout.session.completed"})
        request = _fake_request(mocker)

        result = asyncio.run(billing_webhook(request))

        assert result["status"] == "ok"
        assert result["event"] == "checkout.session.completed"

    def test_verification_failure_becomes_400_not_a_crash(self, monkeypatch, mocker):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
        mocker.patch("app.billing.handle_webhook_event", side_effect=ValueError("signature mismatch"))
        request = _fake_request(mocker)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(billing_webhook(request))
        assert exc.value.status_code == 400
