"""Tests for app/oauth_state.py — HMAC-signed OAuth `state` round-tripping
for the social/Shopify connect+callback flows (app/main.py)."""
import time

import pytest

from app.oauth_state import sign, verify_and_unwrap, OAuthStateError


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("OAUTH_STATE_SECRET", "test-secret-value")


class TestSignAndVerify:
    def test_roundtrip_returns_original_payload(self):
        signed = sign("user-123:profile-456:")
        assert verify_and_unwrap(signed) == "user-123:profile-456:"

    def test_roundtrip_with_plain_user_id(self):
        signed = sign("11111111-1111-1111-1111-111111111111")
        assert verify_and_unwrap(signed) == "11111111-1111-1111-1111-111111111111"

    def test_signed_value_is_not_the_bare_payload(self):
        # Confirms the payload is actually being wrapped/signed, not just
        # passed through unchanged.
        signed = sign("user-123")
        assert signed != "user-123"
        assert signed.startswith("user-123.")


class TestTamperDetection:
    def test_modified_payload_rejected(self):
        signed = sign("victim-user-id")
        payload, ts, sig = signed.rsplit(".", 2)
        tampered = f"attacker-user-id.{ts}.{sig}"
        with pytest.raises(OAuthStateError):
            verify_and_unwrap(tampered)

    def test_modified_signature_rejected(self):
        signed = sign("user-123")
        payload, ts, sig = signed.rsplit(".", 2)
        tampered = f"{payload}.{ts}.{'0' * len(sig)}"
        with pytest.raises(OAuthStateError):
            verify_and_unwrap(tampered)

    def test_signed_with_different_secret_rejected(self, monkeypatch):
        monkeypatch.setenv("OAUTH_STATE_SECRET", "secret-a")
        signed = sign("user-123")
        monkeypatch.setenv("OAUTH_STATE_SECRET", "secret-b")
        with pytest.raises(OAuthStateError):
            verify_and_unwrap(signed)

    def test_malformed_input_rejected(self):
        with pytest.raises(OAuthStateError):
            verify_and_unwrap("not-a-signed-value")

    def test_empty_string_rejected(self):
        with pytest.raises(OAuthStateError):
            verify_and_unwrap("")

    def test_none_rejected(self):
        with pytest.raises(OAuthStateError):
            verify_and_unwrap(None)


class TestExpiry:
    def test_expired_state_rejected(self, monkeypatch):
        import app.oauth_state as oauth_state
        monkeypatch.setattr(oauth_state, "_MAX_AGE_SECONDS", 1)
        signed = sign("user-123")
        time.sleep(1.5)
        with pytest.raises(OAuthStateError):
            verify_and_unwrap(signed)

    def test_fresh_state_accepted(self, monkeypatch):
        import app.oauth_state as oauth_state
        monkeypatch.setattr(oauth_state, "_MAX_AGE_SECONDS", 600)
        signed = sign("user-123")
        assert verify_and_unwrap(signed) == "user-123"


class TestMissingSecret:
    def test_sign_raises_without_secret(self, monkeypatch):
        monkeypatch.delenv("OAUTH_STATE_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="OAUTH_STATE_SECRET"):
            sign("user-123")

    def test_verify_raises_without_secret(self, monkeypatch):
        signed = sign("user-123")
        monkeypatch.delenv("OAUTH_STATE_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="OAUTH_STATE_SECRET"):
            verify_and_unwrap(signed)
