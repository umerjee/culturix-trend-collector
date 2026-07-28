import hashlib
import hmac as hmac_lib

from app.shopify.oauth import get_authorize_url, verify_hmac, exchange_code, is_valid_shop_domain


class TestIsValidShopDomain:
    def test_accepts_well_formed_myshopify_domain(self):
        assert is_valid_shop_domain("my-cool-store.myshopify.com") is True

    def test_rejects_non_myshopify_suffix(self):
        assert is_valid_shop_domain("my-cool-store.com") is False

    def test_rejects_empty_or_malformed(self):
        assert is_valid_shop_domain("") is False
        assert is_valid_shop_domain("https://my-store.myshopify.com") is False
        assert is_valid_shop_domain("../../etc/passwd.myshopify.com!") is False


class TestGetAuthorizeUrl:
    def test_builds_url_with_expected_params(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-123")
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret-abc")

        url = get_authorize_url("test-store.myshopify.com", "https://api.culturix.com/api/shopify/callback", "user-1")

        assert url.startswith("https://test-store.myshopify.com/admin/oauth/authorize?")
        assert "client_id=client-123" in url
        assert "scope=read_products" in url
        assert "state=user-1" in url

    def test_raises_if_client_id_not_set(self, monkeypatch):
        monkeypatch.delenv("SHOPIFY_CLIENT_ID", raising=False)
        try:
            get_authorize_url("test-store.myshopify.com", "https://x/callback", "user-1")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "SHOPIFY_CLIENT_ID" in str(e)


def _sign(params: dict, secret: str) -> str:
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac_lib.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class TestVerifyHmac:
    def test_valid_signature_passes(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret-abc")
        params = {"shop": "test-store.myshopify.com", "code": "abc123", "state": "user-1", "timestamp": "111"}
        params["hmac"] = _sign(params, "secret-abc")

        assert verify_hmac(params) is True

    def test_tampered_param_fails(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret-abc")
        params = {"shop": "test-store.myshopify.com", "code": "abc123", "state": "user-1", "timestamp": "111"}
        params["hmac"] = _sign(params, "secret-abc")
        params["shop"] = "attacker-store.myshopify.com"  # tampered after signing

        assert verify_hmac(params) is False

    def test_wrong_secret_fails(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret-abc")
        params = {"shop": "test-store.myshopify.com", "code": "abc123", "state": "user-1"}
        params["hmac"] = _sign(params, "wrong-secret")

        assert verify_hmac(params) is False

    def test_missing_hmac_fails(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret-abc")
        assert verify_hmac({"shop": "test-store.myshopify.com", "code": "abc123"}) is False

    def test_no_client_secret_configured_fails_closed(self, monkeypatch):
        monkeypatch.delenv("SHOPIFY_CLIENT_SECRET", raising=False)
        params = {"shop": "test-store.myshopify.com", "code": "abc123", "hmac": "anything"}
        assert verify_hmac(params) is False


class TestExchangeCode:
    def test_returns_access_token(self, mocker, monkeypatch):
        monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-123")
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret-abc")
        from unittest.mock import Mock
        resp = Mock(status_code=200)
        resp.json.return_value = {"access_token": "shpat_realtoken", "scope": "read_products"}
        resp.raise_for_status = Mock()
        mock_post = mocker.patch("app.shopify.oauth.httpx.post", return_value=resp)

        token = exchange_code("test-store.myshopify.com", "auth-code-123")

        assert token == "shpat_realtoken"
        sent = mock_post.call_args
        assert sent.kwargs["json"]["client_id"] == "client-123"
        assert sent.kwargs["json"]["client_secret"] == "secret-abc"
        assert sent.kwargs["json"]["code"] == "auth-code-123"

    def test_raises_if_no_access_token_in_response(self, mocker, monkeypatch):
        monkeypatch.setenv("SHOPIFY_CLIENT_ID", "client-123")
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret-abc")
        from unittest.mock import Mock
        resp = Mock(status_code=200)
        resp.json.return_value = {"error": "invalid_request"}
        resp.raise_for_status = Mock()
        mocker.patch("app.shopify.oauth.httpx.post", return_value=resp)

        try:
            exchange_code("test-store.myshopify.com", "bad-code")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "no access_token" in str(e)
