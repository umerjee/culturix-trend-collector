import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.content_profile import ContentProfile
from app.models.generated_content import GeneratedContent
from app.models.generated_media import GeneratedMedia
from app.models.content_post import ContentPost
from app.scheduler import run_auto_publish


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        ContentProfile.__table__, GeneratedContent.__table__,
        GeneratedMedia.__table__, ContentPost.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_profile(session, publish_mode="auto", is_active=True):
    profile = ContentProfile(user_id=uuid.uuid4(), name="Test Profile", publish_mode=publish_mode, is_active=is_active)
    session.add(profile)
    session.commit()
    return profile


class TestRunAutoPublish:
    def test_ignores_non_auto_profiles(self, mocker, db):
        session = db()
        _make_profile(session, publish_mode="manual")
        session.close()

        mock_publish = mocker.patch("app.social.service.publish_and_record")
        run_auto_publish()
        mock_publish.assert_not_called()

    def test_skips_profile_with_no_generated_content(self, mocker, db):
        session = db()
        _make_profile(session, publish_mode="auto")
        session.close()

        mock_publish = mocker.patch("app.social.service.publish_and_record")
        run_auto_publish()
        mock_publish.assert_not_called()

    def test_picks_highest_relevance_live_youtube_idea_and_publishes_existing_video(self, mocker, db):
        session = db()
        profile = _make_profile(session, publish_mode="auto")
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[
                {"hook": "low score", "status": "live", "platform": "YouTube", "relevance_score": 40},
                {"hook": "high score", "status": "live", "platform": "YouTube", "relevance_score": 90},
                {"hook": "stale one", "status": "stale", "platform": "YouTube", "relevance_score": 99},
                {"hook": "unsupported platform", "status": "live", "platform": "Instagram", "relevance_score": 99},
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

        mock_publish = mocker.patch("app.social.service.publish_and_record")
        mock_generate = mocker.patch("app.media.service.run_generation")

        run_auto_publish()

        mock_generate.assert_not_called()  # video already existed — no need to generate
        mock_publish.assert_called_once()
        published_post_id = mock_publish.call_args.args[0]

        session = db()
        try:
            post = session.query(ContentPost).filter_by(id=uuid.UUID(published_post_id)).first()
            assert post.generated_content_id == content_id
            assert post.idea_index == 1  # the highest-relevance_score "live" YouTube idea
            assert post.created_via == "published"
        finally:
            session.close()

    def test_tiktok_idea_is_now_eligible_and_posted_with_tiktok_platform_key(self, mocker, db):
        session = db()
        profile = _make_profile(session, publish_mode="auto")
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[
                {"hook": "youtube idea", "status": "live", "platform": "YouTube", "relevance_score": 50},
                {"hook": "tiktok idea", "status": "live", "platform": "TikTok", "relevance_score": 90},
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

        mock_publish = mocker.patch("app.social.service.publish_and_record")
        run_auto_publish()

        mock_publish.assert_called_once()
        published_post_id = mock_publish.call_args.args[0]

        session = db()
        try:
            post = session.query(ContentPost).filter_by(id=uuid.UUID(published_post_id)).first()
            assert post.idea_index == 1  # the higher-scoring TikTok idea, not the YouTube one
            assert post.platform == "tiktok"
        finally:
            session.close()

    def test_excludes_non_video_medium_idea_even_if_platform_is_youtube(self, mocker, db):
        session = db()
        profile = _make_profile(session, publish_mode="auto")
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[
                {"hook": "photo idea", "status": "live", "platform": "YouTube", "relevance_score": 99, "medium": "photo"},
                {"hook": "video idea", "status": "live", "platform": "YouTube", "relevance_score": 50, "medium": "video"},
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
        session.close()

        mock_publish = mocker.patch("app.social.service.publish_and_record")
        run_auto_publish()

        # Only the video-medium idea (index 1) is eligible, despite the photo
        # idea having a higher relevance_score — Kling+YouTube publish only
        # makes sense for actual video content.
        mock_publish.assert_called_once()

    def test_skips_already_posted_idea_and_falls_through_to_next_candidate(self, mocker, db):
        session = db()
        profile = _make_profile(session, publish_mode="auto")
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[
                {"hook": "already posted", "status": "live", "platform": "YouTube", "relevance_score": 99},
                {"hook": "not yet posted", "status": "live", "platform": "YouTube", "relevance_score": 50},
            ],
        )
        session.add(content)
        session.commit()
        session.add(ContentPost(
            generated_content_id=content.id, idea_index=0, user_id=profile.user_id,
            platform="youtube", created_via="published", status="tracked",
        ))
        media = GeneratedMedia(
            generated_content_id=content.id, idea_index=1, media_type="video",
            provider="kling", status="done", asset_url="https://example.com/v.mp4",
        )
        session.add(media)
        session.commit()
        session.close()

        mock_publish = mocker.patch("app.social.service.publish_and_record")
        run_auto_publish()

        mock_publish.assert_called_once()

    def test_generates_video_first_when_missing_then_publishes(self, mocker, db):
        session = db()
        profile = _make_profile(session, publish_mode="auto")
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[{"hook": "needs video", "status": "live", "platform": "YouTube", "relevance_score": 80}],
        )
        session.add(content)
        session.commit()
        session.close()

        def fake_generate(row_id, **kwargs):
            s = db()
            try:
                m = s.query(GeneratedMedia).filter_by(id=uuid.UUID(row_id)).first()
                m.status = "done"
                m.asset_url = "https://example.com/generated.mp4"
                s.commit()
            finally:
                s.close()

        mock_generate = mocker.patch("app.media.service.run_generation", side_effect=fake_generate)
        mock_publish = mocker.patch("app.social.service.publish_and_record")

        run_auto_publish()

        mock_generate.assert_called_once()
        mock_publish.assert_called_once()

    def test_generation_failure_skips_profile_without_publishing(self, mocker, db):
        session = db()
        profile = _make_profile(session, publish_mode="auto")
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[{"hook": "video fails", "status": "live", "platform": "YouTube", "relevance_score": 80}],
        )
        session.add(content)
        session.commit()
        session.close()

        # run_generation leaves the row status "pending" on failure — never flips to "done"
        mock_generate = mocker.patch("app.media.service.run_generation")
        mock_publish = mocker.patch("app.social.service.publish_and_record")

        run_auto_publish()

        mock_generate.assert_called_once()
        mock_publish.assert_not_called()
