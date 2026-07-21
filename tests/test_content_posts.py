import os
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

from app.db import Base
from app.models.connected_account import ConnectedAccount
from app.models.content_post import ContentPost
from app.models.content_post_snapshot import ContentPostSnapshot
from app.models.generated_content import GeneratedContent
from app.models.generated_media import GeneratedMedia
from app.social.crypto import encrypt
from app.social.base import PostMetrics
from app.social.service import fetch_and_record, publish_and_record


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        ConnectedAccount.__table__, ContentPost.__table__, ContentPostSnapshot.__table__,
        GeneratedContent.__table__, GeneratedMedia.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_connected_account(session, user_id, platform="youtube", expires_in_future=True):
    account = ConnectedAccount(
        user_id=user_id, platform=platform,
        access_token=encrypt("plain-access-token"),
        refresh_token=encrypt("plain-refresh-token"),
        token_expires_at=datetime.utcnow() + timedelta(hours=1) if expires_in_future else datetime.utcnow() - timedelta(hours=1),
        status="active",
    )
    session.add(account)
    session.commit()
    return account


class TestFetchAndRecord:
    def test_success_writes_snapshot_and_updates_post(self, mocker, db):
        session = db()
        user_id = uuid.uuid4()
        _make_connected_account(session, user_id)
        post = ContentPost(
            generated_content_id=uuid.uuid4(), idea_index=0, user_id=user_id,
            platform="youtube", post_url="https://youtu.be/abc123DEF45",
            created_via="manual", status="pending",
        )
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        mock_provider = mocker.Mock()
        mock_provider.fetch_post_metrics.return_value = PostMetrics(
            platform_post_id="abc123DEF45", views=500, likes=20, comments=3, shares=None
        )
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        fetch_and_record(post_id)

        session = db()
        try:
            updated = session.query(ContentPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "tracked"
            assert updated.latest_views == 500
            assert updated.latest_likes == 20
            assert session.query(ContentPostSnapshot).filter_by(content_post_id=updated.id).count() == 1
        finally:
            session.close()

    def test_no_connected_account_marks_needs_reconnect(self, mocker, db):
        session = db()
        user_id = uuid.uuid4()  # no ConnectedAccount created for this user
        post = ContentPost(
            generated_content_id=uuid.uuid4(), idea_index=0, user_id=user_id,
            platform="youtube", post_url="https://youtu.be/abc123DEF45",
            created_via="manual", status="pending",
        )
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        fetch_and_record(post_id)

        session = db()
        try:
            updated = session.query(ContentPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "needs_reconnect"
        finally:
            session.close()

    def test_provider_error_marks_failed_with_message(self, mocker, db):
        session = db()
        user_id = uuid.uuid4()
        _make_connected_account(session, user_id)
        post = ContentPost(
            generated_content_id=uuid.uuid4(), idea_index=0, user_id=user_id,
            platform="youtube", post_url="https://youtu.be/abc123DEF45",
            created_via="manual", status="pending",
        )
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        mock_provider = mocker.Mock()
        mock_provider.fetch_post_metrics.side_effect = RuntimeError("YouTube API down")
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        fetch_and_record(post_id)

        session = db()
        try:
            updated = session.query(ContentPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "failed"
            assert "YouTube API down" in updated.error
        finally:
            session.close()


class TestPublishAndRecord:
    def test_success_creates_tracked_post_with_snapshot(self, mocker, db):
        session = db()
        user_id = uuid.uuid4()
        _make_connected_account(session, user_id)
        content = GeneratedContent(
            user_id=user_id, content_ideas=[{"hook": "Test hook", "caption": "Test caption"}],
        )
        session.add(content)
        session.commit()
        media = GeneratedMedia(
            generated_content_id=content.id, idea_index=0, media_type="video",
            provider="kling", status="done", asset_url="https://example.com/video.mp4",
        )
        session.add(media)
        post = ContentPost(
            generated_content_id=content.id, idea_index=0, user_id=user_id,
            platform="youtube", created_via="published", status="pending",
        )
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        mocker.patch("app.social.service.httpx.get", return_value=mocker.Mock(
            content=b"fake-video-bytes", raise_for_status=mocker.Mock()
        ))
        mock_provider = mocker.Mock()
        mock_provider.publish.return_value = PostMetrics(platform_post_id="newVid1", views=0, likes=0, comments=0)
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        publish_and_record(post_id)

        session = db()
        try:
            updated = session.query(ContentPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "tracked"
            assert updated.platform_post_id == "newVid1"
            assert updated.post_url == "https://www.youtube.com/watch?v=newVid1"
            assert updated.posted_at is not None
            assert updated.tracking_until is not None
            assert session.query(ContentPostSnapshot).filter_by(content_post_id=updated.id).count() == 1
        finally:
            session.close()

    def test_no_finished_video_marks_failed(self, mocker, db):
        session = db()
        user_id = uuid.uuid4()
        _make_connected_account(session, user_id)
        content = GeneratedContent(user_id=user_id, content_ideas=[{"hook": "Test hook"}])
        session.add(content)
        session.commit()
        # No GeneratedMedia row at all — nothing to publish
        post = ContentPost(
            generated_content_id=content.id, idea_index=0, user_id=user_id,
            platform="youtube", created_via="published", status="pending",
        )
        session.add(post)
        session.commit()
        post_id = str(post.id)
        session.close()

        publish_and_record(post_id)

        session = db()
        try:
            updated = session.query(ContentPost).filter_by(id=uuid.UUID(post_id)).first()
            assert updated.status == "failed"
            assert "video" in updated.error.lower()
        finally:
            session.close()
