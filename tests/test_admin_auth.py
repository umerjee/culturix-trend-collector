"""Tests for app/admin_auth.py's shared-secret dependencies."""
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
    def test_raises_403_when_secret_unset(self, monkeypatch):
        monkeypatch.setattr(admin_auth, "INTERNAL_API_SECRET", "")
        with pytest.raises(HTTPException) as exc_info:
            admin_auth.require_internal_secret(x_internal_secret="anything-or-nothing")
        assert exc_info.value.status_code == 403

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
