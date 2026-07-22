import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

from app.db import Base
from app.models.connected_account import ConnectedAccount
from app.social.base import AccountInfo
from app.social.crypto import encrypt
from app.social.service import resolve_active_account, test_connection as run_test_connection, _post_url


@pytest.fixture
def db_session():
    """In-memory SQLite standing in for the app's Postgres DB — real ORM
    behavior (unique constraints, NULL handling) without hand-mocking query
    chains, matching this codebase's existing fixture pattern (see
    tests/test_trend_historian.py's historian_db)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ConnectedAccount.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()
    yield session
    session.close()


class TestResolveActiveAccount:
    def test_prefers_profile_bound_account_over_legacy(self, db_session):
        user_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        db_session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=None, status="active",
            access_token="legacy-token",
        ))
        db_session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=profile_id, status="active",
            access_token="bound-token",
        ))
        db_session.commit()

        account = resolve_active_account(db_session, user_id, "youtube", content_profile_id=profile_id)

        assert account.access_token == "bound-token"

    def test_falls_back_to_legacy_account_when_no_profile_bound_account_exists(self, db_session):
        user_id = uuid.uuid4()
        other_profile_id = uuid.uuid4()
        db_session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=None, status="active",
            access_token="legacy-token",
        ))
        db_session.commit()

        account = resolve_active_account(db_session, user_id, "youtube", content_profile_id=other_profile_id)

        assert account.access_token == "legacy-token"

    def test_no_content_profile_id_resolves_legacy_account_directly(self, db_session):
        user_id = uuid.uuid4()
        db_session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=None, status="active",
            access_token="legacy-token",
        ))
        db_session.commit()

        account = resolve_active_account(db_session, user_id, "youtube", content_profile_id=None)

        assert account.access_token == "legacy-token"

    def test_two_profiles_resolve_to_their_own_distinct_accounts(self, db_session):
        # Regression test for the actual reported gap: two 'auto' profiles on
        # one user must each publish to their own dedicated account, not
        # silently share a single connection.
        user_id = uuid.uuid4()
        profile_a = uuid.uuid4()
        profile_b = uuid.uuid4()
        db_session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=profile_a, status="active",
            access_token="account-a",
        ))
        db_session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=profile_b, status="active",
            access_token="account-b",
        ))
        db_session.commit()

        account_a = resolve_active_account(db_session, user_id, "youtube", content_profile_id=profile_a)
        account_b = resolve_active_account(db_session, user_id, "youtube", content_profile_id=profile_b)

        assert account_a.access_token == "account-a"
        assert account_b.access_token == "account-b"

    def test_no_account_at_all_returns_none(self, db_session):
        account = resolve_active_account(db_session, uuid.uuid4(), "youtube", content_profile_id=None)
        assert account is None

    def test_ignores_inactive_profile_bound_account(self, db_session):
        user_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        db_session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=profile_id, status="revoked",
            access_token="revoked-token",
        ))
        db_session.commit()

        account = resolve_active_account(db_session, user_id, "youtube", content_profile_id=profile_id)

        assert account is None


class TestTestConnection:
    def _make_account(self, session, platform="youtube"):
        account = ConnectedAccount(
            user_id=uuid.uuid4(), platform=platform,
            access_token=encrypt("plain-access-token"),
            refresh_token=encrypt("plain-refresh-token"),
            token_expires_at=datetime.utcnow() + timedelta(hours=1),
            status="active",
        )
        session.add(account)
        session.commit()
        return account

    def test_success_writes_ok_status_and_refreshes_identity(self, mocker, db_session):
        account = self._make_account(db_session)
        mock_provider = mocker.Mock()
        mock_provider.verify.return_value = AccountInfo(platform_account_id="chan-1", platform_username="New Name")
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        result = run_test_connection(db_session, account)

        assert result == {"ok": True, "platform_username": "New Name"}
        assert account.last_test_status == "ok"
        assert account.last_tested_at is not None
        assert account.last_test_error is None
        assert account.platform_username == "New Name"
        assert account.platform_account_id == "chan-1"

    def test_verify_failure_marks_error_status(self, mocker, db_session):
        account = self._make_account(db_session)
        mock_provider = mocker.Mock()
        mock_provider.verify.side_effect = RuntimeError("No channel found")
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        result = run_test_connection(db_session, account)

        assert result["ok"] is False
        assert account.last_test_status == "error"
        assert account.last_test_error == "No channel found"
        assert account.last_tested_at is not None

    def test_expired_token_without_refresh_token_marks_error_with_reconnect_reason(self, mocker, db_session):
        account = ConnectedAccount(
            user_id=uuid.uuid4(), platform="youtube",
            access_token=encrypt("plain-access-token"),
            refresh_token=None,
            token_expires_at=datetime.utcnow() - timedelta(hours=1),
            status="active",
        )
        db_session.add(account)
        db_session.commit()

        result = run_test_connection(db_session, account)

        assert result["ok"] is False
        assert "reconnect" in result["reason"].lower()
        assert account.last_test_status == "error"
        assert account.status == "needs_reconnect"


class TestPostUrl:
    def test_youtube_constructs_watch_url_from_bare_id(self):
        assert _post_url("youtube", "abc123DEF45") == "https://www.youtube.com/watch?v=abc123DEF45"

    def test_tiktok_passes_through_full_share_url_unchanged(self):
        # TikTokProvider.publish() already returns the full share URL as
        # platform_post_id (constructing it needs the username, which isn't
        # available here) — must not be re-wrapped or mangled.
        url = "https://www.tiktok.com/@creator/video/987654321"
        assert _post_url("tiktok", url) == url

    def test_instagram_passes_through_full_permalink_unchanged(self):
        url = "https://www.instagram.com/reel/Cxyz123abc/#mid=17895695668004550"
        assert _post_url("instagram", url) == url

    def test_twitter_constructs_status_url_from_tweet_id(self):
        assert _post_url("twitter", "1234567890") == "https://x.com/i/web/status/1234567890"

    def test_unknown_platform_returns_none(self):
        assert _post_url("unknown_platform", "some-id") is None

    def test_no_post_id_returns_none_regardless_of_platform(self):
        assert _post_url("youtube", None) is None
        assert _post_url("tiktok", None) is None
