import uuid
from datetime import datetime, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.content_profile import ContentProfile
from app.models.generated_content import GeneratedContent
from app.scheduler import run_digest_dispatch

# A fixed Wednesday (weekday()==2) so weekly-profile tests are deterministic
# regardless of when the suite actually runs.
_WEDNESDAY_NOON = datetime(2026, 7, 22, 12, 0, 0)
assert _WEDNESDAY_NOON.weekday() == 2


@pytest.fixture
def dispatch_db(mocker):
    """In-memory SQLite standing in for the app's Postgres DB — same pattern
    as tests/test_trend_historian.py's historian_db and
    tests/test_social_service.py's db_session fixtures."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ContentProfile.__table__, GeneratedContent.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_profile(session, **overrides):
    defaults = dict(
        user_id=uuid.uuid4(), name="Test", is_active=True,
        delivery_freq="daily", delivery_time="09:00", delivery_day_of_week=0,
        publish_mode="manual",
    )
    defaults.update(overrides)
    profile = ContentProfile(**defaults)
    session.add(profile)
    session.commit()
    return profile


def _make_content(session, profile_id, **overrides):
    defaults = dict(
        user_id=uuid.uuid4(), content_profile_id=profile_id, trend_date=date(2026, 7, 22),
        clusters=[{"name": "Trend A"}], content_ideas=[{"hook": "hook 1"}], delivered=False,
        generated_at=_WEDNESDAY_NOON,
    )
    defaults.update(overrides)
    content = GeneratedContent(**defaults)
    session.add(content)
    session.commit()
    return content


class TestRunDigestDispatch:
    def test_daily_profile_sends_once_time_reached(self, dispatch_db, mocker):
        mock_send = mocker.patch("app.pipeline.nodes.digest_writer._send_email")
        mocker.patch("app.pipeline.nodes.digest_writer._get_user_email", return_value="user@example.com")
        mocker.patch("app.pipeline.nodes.digest_writer._render_email", return_value="<html></html>")

        session = dispatch_db()
        profile = _make_profile(session, delivery_time="09:00")
        _make_content(session, profile.id)
        profile_id = profile.id
        session.close()

        run_digest_dispatch(now=_WEDNESDAY_NOON)  # 12:00, past the 09:00 delivery_time

        mock_send.assert_called_once()

        verify = dispatch_db()
        content = verify.query(GeneratedContent).filter_by(content_profile_id=profile_id).first()
        assert content.delivered is True
        verify.close()

    def test_daily_profile_skipped_before_delivery_time(self, dispatch_db, mocker):
        mock_send = mocker.patch("app.pipeline.nodes.digest_writer._send_email")
        mocker.patch("app.pipeline.nodes.digest_writer._get_user_email", return_value="user@example.com")
        mocker.patch("app.pipeline.nodes.digest_writer._render_email", return_value="<html></html>")

        session = dispatch_db()
        profile = _make_profile(session, delivery_time="18:00")
        _make_content(session, profile.id)
        session.close()

        run_digest_dispatch(now=_WEDNESDAY_NOON)  # 12:00, before the 18:00 delivery_time

        mock_send.assert_not_called()

    def test_weekly_profile_skipped_on_wrong_weekday(self, dispatch_db, mocker):
        mock_send = mocker.patch("app.pipeline.nodes.digest_writer._send_email")
        mocker.patch("app.pipeline.nodes.digest_writer._get_user_email", return_value="user@example.com")
        mocker.patch("app.pipeline.nodes.digest_writer._render_email", return_value="<html></html>")

        session = dispatch_db()
        # delivery_day_of_week=0 (Monday), but _WEDNESDAY_NOON is a Wednesday (2)
        profile = _make_profile(session, delivery_freq="weekly", delivery_day_of_week=0, delivery_time="09:00")
        _make_content(session, profile.id)
        session.close()

        run_digest_dispatch(now=_WEDNESDAY_NOON)

        mock_send.assert_not_called()

    def test_weekly_profile_sends_on_matching_weekday(self, dispatch_db, mocker):
        mock_send = mocker.patch("app.pipeline.nodes.digest_writer._send_email")
        mocker.patch("app.pipeline.nodes.digest_writer._get_user_email", return_value="user@example.com")
        mocker.patch("app.pipeline.nodes.digest_writer._render_email", return_value="<html></html>")

        session = dispatch_db()
        profile = _make_profile(session, delivery_freq="weekly", delivery_day_of_week=2, delivery_time="09:00")
        _make_content(session, profile.id)
        session.close()

        run_digest_dispatch(now=_WEDNESDAY_NOON)

        mock_send.assert_called_once()

    def test_already_delivered_content_is_not_resent(self, dispatch_db, mocker):
        mock_send = mocker.patch("app.pipeline.nodes.digest_writer._send_email")
        mocker.patch("app.pipeline.nodes.digest_writer._get_user_email", return_value="user@example.com")
        mocker.patch("app.pipeline.nodes.digest_writer._render_email", return_value="<html></html>")

        session = dispatch_db()
        profile = _make_profile(session, delivery_time="09:00")
        _make_content(session, profile.id, delivered=True)
        session.close()

        run_digest_dispatch(now=_WEDNESDAY_NOON)

        mock_send.assert_not_called()

    def test_no_content_for_today_is_skipped_without_crashing(self, dispatch_db, mocker):
        mock_send = mocker.patch("app.pipeline.nodes.digest_writer._send_email")
        mocker.patch("app.pipeline.nodes.digest_writer._get_user_email", return_value="user@example.com")
        mocker.patch("app.pipeline.nodes.digest_writer._render_email", return_value="<html></html>")

        session = dispatch_db()
        _make_profile(session, delivery_time="09:00")
        session.close()

        run_digest_dispatch(now=_WEDNESDAY_NOON)

        mock_send.assert_not_called()

    def test_inactive_profile_is_skipped(self, dispatch_db, mocker):
        mock_send = mocker.patch("app.pipeline.nodes.digest_writer._send_email")
        mocker.patch("app.pipeline.nodes.digest_writer._get_user_email", return_value="user@example.com")
        mocker.patch("app.pipeline.nodes.digest_writer._render_email", return_value="<html></html>")

        session = dispatch_db()
        profile = _make_profile(session, is_active=False, delivery_time="09:00")
        _make_content(session, profile.id)
        session.close()

        run_digest_dispatch(now=_WEDNESDAY_NOON)

        mock_send.assert_not_called()
