import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.connected_account import ConnectedAccount
from app.social.service import resolve_active_account


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
