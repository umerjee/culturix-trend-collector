"""Tests for app/admin_auth.py's shared-secret dependencies —
require_admin_secret (existing, fail-closed) and require_internal_secret
(new, deliberately fail-open when unconfigured — see that function's own
docstring for why)."""
import pytest
from fastapi import HTTPException

import app.admin_auth as admin_auth


class TestRequireAdminSecret:
    def test_raises_403_when_secret_unset(self, monkeypatch):
        monkeypatch.setattr(admin_auth, "ADMIN_API_SECRET", "")
        with pytest.raises(HTTPException) as exc_info:
            admin_auth.require_admin_secret(x_admin_secret="anything")
        assert exc_info.value.status_code == 403

    def test_raises_403_on_mismatch(self, monkeypatch):
        monkeypatch.setattr(admin_auth, "ADMIN_API_SECRET", "correct-secret")
        with pytest.raises(HTTPException) as exc_info:
            admin_auth.require_admin_secret(x_admin_secret="wrong-secret")
        assert exc_info.value.status_code == 403

    def test_passes_on_match(self, monkeypatch):
        monkeypatch.setattr(admin_auth, "ADMIN_API_SECRET", "correct-secret")
        admin_auth.require_admin_secret(x_admin_secret="correct-secret")  # no raise


class TestRequireInternalSecret:
    def test_passes_through_when_unset_fail_open(self, monkeypatch):
        # Deliberately fail-open — see require_internal_secret's docstring.
        # This must NOT raise even with a garbage header, since the whole
        # point is to not break the live app before the secret is
        # configured on both Railway and Vercel.
        monkeypatch.setattr(admin_auth, "INTERNAL_API_SECRET", "")
        admin_auth.require_internal_secret(x_internal_secret="anything-or-nothing")  # no raise

    def test_raises_403_on_mismatch_once_configured(self, monkeypatch):
        monkeypatch.setattr(admin_auth, "INTERNAL_API_SECRET", "correct-secret")
        with pytest.raises(HTTPException) as exc_info:
            admin_auth.require_internal_secret(x_internal_secret="wrong-secret")
        assert exc_info.value.status_code == 403

    def test_passes_on_match_once_configured(self, monkeypatch):
        monkeypatch.setattr(admin_auth, "INTERNAL_API_SECRET", "correct-secret")
        admin_auth.require_internal_secret(x_internal_secret="correct-secret")  # no raise

    def test_empty_header_rejected_once_configured(self, monkeypatch):
        monkeypatch.setattr(admin_auth, "INTERNAL_API_SECRET", "correct-secret")
        with pytest.raises(HTTPException) as exc_info:
            admin_auth.require_internal_secret(x_internal_secret="")
        assert exc_info.value.status_code == 403
