"""Tests for app/services/culturetoon_analytics.py — the Phase 8 analytics
feedback loop (docs/culturix-comedy-architecture.md §3.11/§7). Computed
live at script-generation time, not via a scheduled job — see this
module's own docstring for why."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.toon_post import ToonPost
from app.models.toon import Toon
from app.models.toon_script import ToonScript
from app.services.culturetoon_analytics import (
    compute_performance_summary, get_cast_performance_context, _duration_bucket,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ToonPost.__table__, Toon.__table__, ToonScript.__table__])
    return sessionmaker(bind=engine)


def _seed_tracked_post(session, brand_id, variant_id, tone, duration, views, likes, comments, shares):
    script = ToonScript(
        brand_id=brand_id, character_variant_id=variant_id, character_variant_ids=[str(variant_id)],
        tone=tone, total_duration_seconds=duration, shots=[],
    )
    session.add(script)
    session.commit()
    toon = Toon(brand_id=brand_id, character_variant_id=variant_id, script_id=script.id, status="posted")
    session.add(toon)
    session.commit()
    post = ToonPost(
        toon_id=toon.id, brand_id=brand_id, user_id=uuid.uuid4(), platform="tiktok", status="tracked",
        latest_views=views, latest_likes=likes, latest_comments=comments, latest_shares=shares,
    )
    session.add(post)
    session.commit()
    return toon, script, post


class TestDurationBucket:
    def test_buckets(self):
        assert _duration_bucket(5) == "short (<=8s)"
        assert _duration_bucket(12) == "medium (9-15s)"
        assert _duration_bucket(20) == "long (>15s)"
        assert _duration_bucket(None) == "unknown"


class TestComputePerformanceSummary:
    def test_groups_by_cast_tone_and_duration(self, db):
        session = db()
        brand_id = uuid.uuid4()
        variant_id = uuid.uuid4()
        _seed_tracked_post(session, brand_id, variant_id, "funny", 10, views=1000, likes=100, comments=20, shares=10)
        _seed_tracked_post(session, brand_id, variant_id, "funny", 10, views=2000, likes=200, comments=40, shares=20)

        summary = compute_performance_summary(session, brand_id)
        assert len(summary) == 1
        row = summary[0]
        assert row["tone"] == "funny"
        assert row["post_count"] == 2
        assert row["avg_views"] == 1500
        session.close()

    def test_only_tracked_posts_counted(self, db):
        session = db()
        brand_id = uuid.uuid4()
        variant_id = uuid.uuid4()
        _seed_tracked_post(session, brand_id, variant_id, "funny", 10, views=1000, likes=100, comments=20, shares=10)
        # A pending (not yet tracked) post shouldn't be counted
        script2 = ToonScript(brand_id=brand_id, character_variant_id=variant_id, tone="funny", total_duration_seconds=10, shots=[])
        session.add(script2); session.commit()
        toon2 = Toon(brand_id=brand_id, character_variant_id=variant_id, script_id=script2.id, status="ready")
        session.add(toon2); session.commit()
        session.add(ToonPost(toon_id=toon2.id, brand_id=brand_id, user_id=uuid.uuid4(), platform="tiktok", status="pending"))
        session.commit()

        summary = compute_performance_summary(session, brand_id)
        assert sum(r["post_count"] for r in summary) == 1
        session.close()

    def test_zero_views_gives_zero_engagement_not_error(self, db):
        session = db()
        brand_id = uuid.uuid4()
        variant_id = uuid.uuid4()
        _seed_tracked_post(session, brand_id, variant_id, "funny", 10, views=0, likes=0, comments=0, shares=0)

        summary = compute_performance_summary(session, brand_id)
        assert summary[0]["avg_engagement_rate"] == 0.0
        session.close()


class TestGetCastPerformanceContext:
    def test_no_data_returns_empty_string(self, db):
        session = db()
        result = get_cast_performance_context(session, uuid.uuid4(), [uuid.uuid4()])
        assert result == ""
        session.close()

    def test_returns_summary_for_overlapping_cast(self, db):
        session = db()
        brand_id = uuid.uuid4()
        variant_id = uuid.uuid4()
        _seed_tracked_post(session, brand_id, variant_id, "funny", 10, views=1000, likes=100, comments=20, shares=10)

        result = get_cast_performance_context(session, brand_id, [variant_id])
        assert "funny" in result
        assert "1000" in result or "1,000" in result
        session.close()

    def test_no_overlap_returns_empty(self, db):
        session = db()
        brand_id = uuid.uuid4()
        variant_id = uuid.uuid4()
        other_variant_id = uuid.uuid4()
        _seed_tracked_post(session, brand_id, variant_id, "funny", 10, views=1000, likes=100, comments=20, shares=10)

        result = get_cast_performance_context(session, brand_id, [other_variant_id])
        assert result == ""
        session.close()

    def test_failure_returns_empty_not_raises(self, db, mocker):
        mocker.patch(
            "app.services.culturetoon_analytics.compute_performance_summary",
            side_effect=RuntimeError("db error"),
        )
        session = db()
        result = get_cast_performance_context(session, uuid.uuid4(), [uuid.uuid4()])
        assert result == ""
        session.close()
