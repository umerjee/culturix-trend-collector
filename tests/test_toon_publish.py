"""Tests for the CultureToons publish/track background tasks
(app/social/service.py's publish_toon_and_record/fetch_toon_and_record) —
mirrors tests/test_content_posts.py's structure for the ContentPost
originals, since these are the same shape against a different pair of
models (ToonPost/Toon instead of ContentPost/GeneratedMedia)."""
import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

from app.db import Base
from app.models.connected_account import ConnectedAccount
from app.models.toon_post import ToonPost
from app.models.toon import Toon
from app.models.toon_script import ToonScript
from app.social.crypto import encrypt
from app.social.base import PostMetrics
from app.social.service import fetch_toon_and_record, publish_toon_and_record


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        ConnectedAccount.__table__, ToonPost.__table__, Toon.__table__, ToonScript.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_connected_account(session, user_id, brand_id, platform="tiktok"):
    account = ConnectedAccount(
        user_id=user_id, character_brand_id=brand_id, platform=platform,
        access_token=encrypt("plain-access-token"),
        refresh_token=encrypt("plain-refresh-token"),
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
        status="active",
    )
    session.add(account)
    session.commit()
    return account


def _make_toon_and_script(session, brand_id, final_video_url="https://example.com/v.mp4"):
    script = ToonScript(brand_id=brand_id, hook_line="A funny hook")
    session.add(script)
    session.commit()
    toon = Toon(
        brand_id=brand_id, character_variant_id=uuid.uuid4(), script_id=script.id,
        final_video_url=final_video_url, status="ready",
    )
    session.add(toon)
    session.commit()
    return toon


class TestFetchToonAndRecord:
    def test_success_updates_post(self, mocker, db):
        session = db()
        user_id, brand_id = uuid.uuid4(), uuid.uuid4()
        _make_connected_account(session, user_id, brand_id)
        toon = _make_toon_and_script(session, brand_id)
        post = ToonPost(toon_id=toon.id, brand_id=brand_id, user_id=user_id, platform="tiktok", status="pending")
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        mock_provider = mocker.Mock()
        mock_provider.fetch_post_metrics.return_value = PostMetrics(
            platform_post_id="abc123", views=500, likes=20, comments=3, shares=None
        )
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        fetch_toon_and_record(post_id)

        session = db()
        try:
            updated = session.query(ToonPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "tracked"
            assert updated.latest_views == 500
        finally:
            session.close()

    def test_no_connected_account_marks_needs_reconnect(self, mocker, db):
        session = db()
        user_id, brand_id = uuid.uuid4(), uuid.uuid4()
        toon = _make_toon_and_script(session, brand_id)
        post = ToonPost(toon_id=toon.id, brand_id=brand_id, user_id=user_id, platform="tiktok", status="pending")
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        fetch_toon_and_record(post_id)

        session = db()
        try:
            updated = session.query(ToonPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "needs_reconnect"
        finally:
            session.close()


class TestPublishToonAndRecord:
    def test_success_marks_tracked_and_syncs_toon(self, mocker, db):
        session = db()
        user_id, brand_id = uuid.uuid4(), uuid.uuid4()
        _make_connected_account(session, user_id, brand_id)
        toon = _make_toon_and_script(session, brand_id)
        post = ToonPost(toon_id=toon.id, brand_id=brand_id, user_id=user_id, platform="tiktok", status="pending")
        session.add(post)
        session.commit()
        post_id, toon_id = str(post.id), str(toon.id)
        session.close()

        mocker.patch("app.social.service.httpx.get", return_value=mocker.Mock(content=b"video-bytes", raise_for_status=lambda: None))
        mock_provider = mocker.Mock()
        mock_provider.publish.return_value = PostMetrics(
            platform_post_id="xyz789", views=0, likes=0, comments=0, shares=None
        )
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        publish_toon_and_record(post_id)

        session = db()
        try:
            updated_post = session.query(ToonPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated_post.status == "tracked"
            assert updated_post.platform_post_id == "xyz789"
            assert updated_post.posted_at is not None

            updated_toon = session.query(Toon).filter_by(id=uuid.UUID(toon_id)).first()
            assert updated_toon.status == "posted"
            assert updated_toon.platform == "tiktok"
            assert updated_toon.posted_at is not None
        finally:
            session.close()

    def test_no_final_video_marks_failed(self, mocker, db):
        session = db()
        user_id, brand_id = uuid.uuid4(), uuid.uuid4()
        _make_connected_account(session, user_id, brand_id)
        toon = _make_toon_and_script(session, brand_id, final_video_url=None)
        post = ToonPost(toon_id=toon.id, brand_id=brand_id, user_id=user_id, platform="tiktok", status="pending")
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        publish_toon_and_record(post_id)

        session = db()
        try:
            updated = session.query(ToonPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "failed"
            assert "final video" in updated.error.lower()
        finally:
            session.close()

    def test_no_connected_account_marks_needs_reconnect(self, mocker, db):
        session = db()
        user_id, brand_id = uuid.uuid4(), uuid.uuid4()
        toon = _make_toon_and_script(session, brand_id)
        post = ToonPost(toon_id=toon.id, brand_id=brand_id, user_id=user_id, platform="tiktok", status="pending")
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        publish_toon_and_record(post_id)

        session = db()
        try:
            updated = session.query(ToonPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "needs_reconnect"
        finally:
            session.close()
