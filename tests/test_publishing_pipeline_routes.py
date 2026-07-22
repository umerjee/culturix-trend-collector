import os
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

from app.db import Base
from app.models.connected_account import ConnectedAccount
from app.models.content_profile import ContentProfile
from app.models.generated_content import GeneratedContent
from app.models.content_post import ContentPost
from app.social.base import AccountInfo
from app.social.crypto import encrypt
from app.main import (
    test_social_connection as run_test_social_connection,
    next_auto_publish,
    list_all_content_posts,
)


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        ConnectedAccount.__table__, ContentProfile.__table__,
        GeneratedContent.__table__, ContentPost.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestSocialConnectionTestEndpoint:
    def test_unsupported_platform_404s(self, db):
        with pytest.raises(HTTPException) as exc:
            run_test_social_connection("myspace", user_id=str(uuid.uuid4()))
        assert exc.value.status_code == 404

    def test_no_connected_account_returns_400(self, db):
        with pytest.raises(HTTPException) as exc:
            run_test_social_connection("youtube", user_id=str(uuid.uuid4()))
        assert exc.value.status_code == 400

    def test_success_returns_ok_true(self, mocker, db):
        session = db()
        user_id = uuid.uuid4()
        session.add(ConnectedAccount(
            user_id=user_id, platform="youtube",
            access_token=encrypt("plain-token"), status="active",
        ))
        session.commit()
        session.close()

        mock_provider = mocker.Mock()
        mock_provider.verify.return_value = AccountInfo(platform_account_id="c1", platform_username="Chan")
        mocker.patch("app.social.service._get_provider", return_value=mock_provider)

        result = run_test_social_connection("youtube", user_id=str(user_id))

        assert result == {"ok": True, "platform_username": "Chan"}


class TestNextAutoPublish:
    def test_profile_not_found_404s(self, db):
        with pytest.raises(HTTPException) as exc:
            next_auto_publish(str(uuid.uuid4()), str(uuid.uuid4()))
        assert exc.value.status_code == 404

    def test_non_auto_profile_returns_not_auto_mode(self, db):
        session = db()
        profile = ContentProfile(user_id=uuid.uuid4(), name="P", publish_mode="manual")
        session.add(profile)
        session.commit()
        user_id, profile_id = profile.user_id, profile.id
        session.close()

        result = next_auto_publish(str(user_id), str(profile_id))

        assert result == {"candidate": None, "reason": "not_auto_mode"}

    def test_auto_profile_with_no_eligible_idea_returns_reason(self, db):
        session = db()
        profile = ContentProfile(user_id=uuid.uuid4(), name="P", publish_mode="auto")
        session.add(profile)
        session.commit()
        user_id, profile_id = profile.user_id, profile.id
        session.close()

        result = next_auto_publish(str(user_id), str(profile_id))

        assert result == {"candidate": None, "reason": "no_eligible_idea"}

    def test_auto_profile_with_eligible_idea_returns_candidate_preview(self, db):
        session = db()
        profile = ContentProfile(user_id=uuid.uuid4(), name="P", publish_mode="auto")
        session.add(profile)
        session.commit()
        content = GeneratedContent(
            user_id=profile.user_id, content_profile_id=profile.id, generated_at=datetime.utcnow(),
            content_ideas=[
                {"hook": "low", "status": "live", "platform": "YouTube", "relevance_score": 10},
                {"hook": "high", "status": "live", "platform": "YouTube", "relevance_score": 90},
            ],
        )
        session.add(content)
        session.commit()
        user_id, profile_id = profile.user_id, profile.id
        session.close()

        result = next_auto_publish(str(user_id), str(profile_id))

        assert result["candidate"]["hook"] == "high"
        assert result["candidate"]["platform"] == "youtube"
        assert result["scheduled_for"] == "~11:00 UTC daily"


class TestListAllContentPostsProfileFilter:
    def test_filters_to_only_the_given_profile(self, db):
        session = db()
        user_id = uuid.uuid4()
        profile_a = uuid.uuid4()
        profile_b = uuid.uuid4()
        content_a = GeneratedContent(user_id=user_id, content_profile_id=profile_a, content_ideas=[{"hook": "a"}])
        content_b = GeneratedContent(user_id=user_id, content_profile_id=profile_b, content_ideas=[{"hook": "b"}])
        session.add_all([content_a, content_b])
        session.commit()
        session.add_all([
            ContentPost(generated_content_id=content_a.id, idea_index=0, user_id=user_id,
                        platform="youtube", created_via="published", status="tracked"),
            ContentPost(generated_content_id=content_b.id, idea_index=0, user_id=user_id,
                        platform="youtube", created_via="published", status="tracked"),
        ])
        session.commit()
        session.close()

        result = list_all_content_posts(str(user_id), content_profile_id=str(profile_a))

        assert len(result) == 1
        assert result[0]["hook"] == "a"
