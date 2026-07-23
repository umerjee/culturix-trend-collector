import os
import uuid
from datetime import datetime

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

from app.db import Base
from app.models.connected_account import ConnectedAccount
from app.models.content_profile import ContentProfile
from app.models.generated_content import GeneratedContent
from app.models.generated_media import GeneratedMedia
from app.models.content_post import ContentPost
from app.social.crypto import encrypt
from app.social.service import compile_caption_text, stage_and_notify
from app.scheduler import run_stage_and_notify
from app.main import stage_content_post, get_stage_info, confirm_content_post_posted, publish_content_post


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        ConnectedAccount.__table__, ContentProfile.__table__,
        GeneratedContent.__table__, GeneratedMedia.__table__, ContentPost.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestCompileCaptionText:
    def test_combines_hook_caption_cta_and_hashtags(self):
        idea = {
            "hook": "Wait for it",
            "caption": "This trend is everywhere right now.",
            "cta": "Follow for more",
            "hashtag_strategy": "#trend #fyp",
        }
        text = compile_caption_text(idea)
        assert "Wait for it" in text
        assert "This trend is everywhere right now." in text
        assert "👉 Follow for more" in text
        assert "#trend #fyp" in text

    def test_missing_fields_dont_crash_or_leave_stray_whitespace(self):
        text = compile_caption_text({"hook": "Only a hook"})
        assert text.strip() == "Only a hook"


class TestStageAndNotify:
    def test_missing_post_is_a_noop(self, db):
        stage_and_notify(str(uuid.uuid4()))  # should not raise

    def test_soft_fails_when_onesignal_unconfigured_but_still_records_attempt(self, mocker, db, monkeypatch):
        monkeypatch.delenv("ONESIGNAL_APP_ID", raising=False)
        monkeypatch.delenv("ONESIGNAL_REST_API_KEY", raising=False)

        session = db()
        post = ContentPost(
            generated_content_id=uuid.uuid4(), idea_index=0, user_id=uuid.uuid4(),
            platform="youtube", created_via="staged", status="staged", caption_text="hello",
        )
        session.add(post)
        session.commit()
        post_id = post.id
        session.close()

        stage_and_notify(str(post_id))

        session = db()
        try:
            row = session.query(ContentPost).filter_by(id=post_id).first()
            assert row.notification_status == "failed"
            assert row.notified_at is not None
            assert row.status == "staged"  # push failure never flips status
        finally:
            session.close()


class TestRunStageAndNotify:
    def _make_profile(self, session, publish_mode="auto"):
        profile = ContentProfile(user_id=uuid.uuid4(), name="P", publish_mode=publish_mode, is_active=True)
        session.add(profile)
        session.commit()
        return profile

    def test_stages_highest_relevance_idea_instead_of_publishing(self, mocker, db):
        session = db()
        profile = self._make_profile(session)
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[
                {"hook": "low", "status": "live", "platform": "YouTube", "relevance_score": 10},
                {"hook": "high", "caption": "c", "status": "live", "platform": "YouTube", "relevance_score": 90},
            ],
        )
        session.add(content)
        session.commit()
        media = GeneratedMedia(
            generated_content_id=content.id, idea_index=1, media_type="video",
            provider="kling", status="done", asset_url="https://example.com/v.mp4",
        )
        session.add(media)
        session.commit()
        content_id = content.id
        session.close()

        mock_stage_notify = mocker.patch("app.social.service.stage_and_notify")
        run_stage_and_notify()

        mock_stage_notify.assert_called_once()
        staged_post_id = mock_stage_notify.call_args.args[0]

        session = db()
        try:
            post = session.query(ContentPost).filter_by(id=uuid.UUID(staged_post_id)).first()
            assert post.idea_index == 1
            assert post.created_via == "staged"
            assert post.status == "staged"
            assert post.caption_text and "high" in post.caption_text
        finally:
            session.close()


class TestStageContentPostRoute:
    def _setup_account_and_media(self, session, user_id, content_profile_id=None):
        session.add(ConnectedAccount(
            user_id=user_id, platform="youtube", content_profile_id=content_profile_id,
            access_token=encrypt("tok"), status="active",
        ))
        session.commit()

    def test_no_connected_account_400s(self, db):
        content = GeneratedContent(user_id=uuid.uuid4(), generated_at=datetime.utcnow(), content_ideas=[{}])
        session = db()
        session.add(content)
        session.commit()
        content_id, user_id = content.id, content.user_id
        session.close()

        with pytest.raises(HTTPException) as exc:
            stage_content_post(
                {"content_id": str(content_id), "idea_index": 0, "user_id": str(user_id), "platform": "youtube"},
                BackgroundTasks(),
            )
        assert exc.value.status_code == 400

    def test_success_creates_staged_post_and_queues_stage_and_notify(self, db):
        session = db()
        user_id = uuid.uuid4()
        self._setup_account_and_media(session, user_id)
        content = GeneratedContent(
            user_id=user_id, generated_at=datetime.utcnow(),
            content_ideas=[{"hook": "h", "caption": "c"}],
        )
        session.add(content)
        session.commit()
        media = GeneratedMedia(
            generated_content_id=content.id, idea_index=0, media_type="video",
            provider="kling", status="done", asset_url="https://example.com/v.mp4",
        )
        session.add(media)
        session.commit()
        content_id = content.id
        session.close()

        bg = BackgroundTasks()
        result = stage_content_post(
            {"content_id": str(content_id), "idea_index": 0, "user_id": str(user_id), "platform": "youtube"}, bg
        )
        assert result["status"] == "staged"
        assert len(bg.tasks) == 1

        session = db()
        try:
            post = session.query(ContentPost).filter_by(id=uuid.UUID(result["content_post_id"])).first()
            assert post.status == "staged"
            assert post.created_via == "staged"
            assert "h" in post.caption_text
        finally:
            session.close()


class TestGetStageInfo:
    def test_not_found_404s(self, db):
        with pytest.raises(HTTPException) as exc:
            get_stage_info(str(uuid.uuid4()))
        assert exc.value.status_code == 404

    def test_returns_video_url_and_caption(self, db):
        session = db()
        post = ContentPost(
            generated_content_id=uuid.uuid4(), idea_index=0, user_id=uuid.uuid4(),
            platform="tiktok", created_via="staged", status="staged", caption_text="my caption",
        )
        session.add(post)
        session.commit()
        media = GeneratedMedia(
            generated_content_id=post.generated_content_id, idea_index=0, media_type="video",
            provider="kling", status="done", asset_url="https://example.com/v.mp4",
        )
        session.add(media)
        session.commit()
        post_id = post.id
        session.close()

        result = get_stage_info(str(post_id))
        assert result["video_url"] == "https://example.com/v.mp4"
        assert result["caption_text"] == "my caption"
        assert result["target_platform"] == "tiktok"


class TestConfirmPosted:
    def test_missing_post_url_400s(self, db):
        with pytest.raises(HTTPException) as exc:
            confirm_content_post_posted(str(uuid.uuid4()), {}, BackgroundTasks())
        assert exc.value.status_code == 400

    def test_success_flips_status_to_pending_and_queues_fetch(self, db):
        session = db()
        post = ContentPost(
            generated_content_id=uuid.uuid4(), idea_index=0, user_id=uuid.uuid4(),
            platform="youtube", created_via="staged", status="staged",
        )
        session.add(post)
        session.commit()
        post_id = post.id
        session.close()

        bg = BackgroundTasks()
        result = confirm_content_post_posted(str(post_id), {"post_url": "https://youtube.com/watch?v=x"}, bg)
        assert result == {"status": "queued"}
        assert len(bg.tasks) == 1

        session = db()
        try:
            row = session.query(ContentPost).filter_by(id=post_id).first()
            assert row.status == "pending"
            assert row.post_url == "https://youtube.com/watch?v=x"
            assert row.tracking_until is not None
        finally:
            session.close()


class TestPublishContentPostGate:
    def test_disabled_by_default_returns_503(self, db, monkeypatch):
        monkeypatch.delenv("ENABLE_DIRECT_PUBLISH", raising=False)
        with pytest.raises(HTTPException) as exc:
            publish_content_post(
                {"content_id": str(uuid.uuid4()), "idea_index": 0, "user_id": str(uuid.uuid4()), "platform": "youtube"},
                BackgroundTasks(),
            )
        assert exc.value.status_code == 503

    def test_enabled_via_flag_proceeds_past_the_gate(self, db, monkeypatch):
        monkeypatch.setenv("ENABLE_DIRECT_PUBLISH", "true")
        # No connected account exists — should get past the gate and fail
        # later (400, "connect your account"), not 503.
        with pytest.raises(HTTPException) as exc:
            publish_content_post(
                {"content_id": str(uuid.uuid4()), "idea_index": 0, "user_id": str(uuid.uuid4()), "platform": "youtube"},
                BackgroundTasks(),
            )
        assert exc.value.status_code == 400
