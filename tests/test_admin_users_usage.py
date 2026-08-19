"""Tests for GET /admin/users's idea-usage counters — proactive_ideas_this_month/
on_demand_ideas_this_month, added so admins can verify plan-tier idea
gating (app/media/quota.py::plan_blocks_extra_ideas) actually reflects
real activity rather than trusting a client-side claim."""
import os
import uuid
from datetime import datetime, timedelta

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.generated_content import GeneratedContent
from app.models.user_profile import UserProfile
from app.models.content_profile import ContentProfile
from app.main import admin_users


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        GeneratedContent.__table__, UserProfile.__table__, ContentProfile.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestAdminUsersIdeaUsage:
    def test_counts_proactive_and_on_demand_separately_this_month(self, db):
        user_id = uuid.uuid4()
        session = db()
        session.add(UserProfile(id=uuid.uuid4(), user_id=user_id, plan="pro"))
        session.add(GeneratedContent(
            id=uuid.uuid4(), user_id=user_id, generated_at=datetime.utcnow(),
            content_ideas=[
                {"cluster_index": 0, "source": "auto"},
                {"cluster_index": 1, "source": "auto"},
                {"cluster_index": 2, "source": "auto"},
                {"cluster_index": 3, "source": "on_demand"},
            ],
        ))
        session.commit()
        session.close()

        result = admin_users()

        user_record = next(u for u in result if u["user_id"] == str(user_id))
        assert user_record["proactive_ideas_this_month"] == 3
        assert user_record["on_demand_ideas_this_month"] == 1

    def test_excludes_ideas_from_before_this_month(self, db):
        user_id = uuid.uuid4()
        last_month = datetime.utcnow().replace(day=1) - timedelta(days=1)
        session = db()
        session.add(UserProfile(id=uuid.uuid4(), user_id=user_id, plan="free"))
        session.add(GeneratedContent(
            id=uuid.uuid4(), user_id=user_id, generated_at=last_month,
            content_ideas=[{"cluster_index": 0, "source": "on_demand"}],
        ))
        session.commit()
        session.close()

        result = admin_users()

        user_record = next(u for u in result if u["user_id"] == str(user_id))
        assert user_record["proactive_ideas_this_month"] == 0
        assert user_record["on_demand_ideas_this_month"] == 0

    def test_zero_usage_when_no_digests_yet(self, db):
        user_id = uuid.uuid4()
        session = db()
        session.add(UserProfile(id=uuid.uuid4(), user_id=user_id, plan="free"))
        session.commit()
        session.close()

        result = admin_users()

        user_record = next(u for u in result if u["user_id"] == str(user_id))
        assert user_record["proactive_ideas_this_month"] == 0
        assert user_record["on_demand_ideas_this_month"] == 0
