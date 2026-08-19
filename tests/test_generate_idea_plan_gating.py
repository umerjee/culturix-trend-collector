"""Tests for POST /api/generate-idea's plan-tier gating — the 3
proactively-generated ideas per digest (PROACTIVE_CLUSTER_COUNT in
content_strategist.py) are free for everyone and never reach this
endpoint; generating an idea for a cluster that doesn't have one yet is
the on-demand pro differentiator this endpoint gates. Same test-setup
convention as tests/test_publishing_pipeline_routes.py: direct import
from app.main (safe — lifespan()'s DDL only runs on real ASGI startup,
not on module import), in-memory SQLite, external calls mocked."""
import os
import uuid

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.generated_content import GeneratedContent
from app.models.user_profile import UserProfile
from app.main import generate_idea_for_trend


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[GeneratedContent.__table__, UserProfile.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_digest(db, user_id, clusters=None, content_ideas=None):
    session = db()
    content = GeneratedContent(
        id=uuid.uuid4(), user_id=user_id,
        clusters=clusters if clusters is not None else [{"name": "Trend A"}, {"name": "Trend B"}],
        content_ideas=content_ideas if content_ideas is not None else [],
    )
    session.add(content)
    session.commit()
    content_id = content.id
    session.close()
    return content_id


def _set_plan(db, user_id, plan):
    session = db()
    session.add(UserProfile(id=uuid.uuid4(), user_id=user_id, plan=plan))
    session.commit()
    session.close()


class TestExistingIdeaBypassesGating:
    def test_returns_existing_idea_for_free_user_without_generating(self, db, mocker):
        # An idea that's already there (e.g. one of the 3 free proactive
        # ones) must never be blocked — this is a read, not a generation.
        mock_generate = mocker.patch("app.pipeline.nodes.content_strategist._generate_ideas_for_clusters")
        user_id = uuid.uuid4()
        _set_plan(db, user_id, "free")
        content_id = _make_digest(
            db, user_id,
            content_ideas=[{"cluster_index": 0, "hook": "existing hook", "source": "auto"}],
        )

        result = generate_idea_for_trend({"content_id": str(content_id), "cluster_index": 0})

        assert result["hook"] == "existing hook"
        mock_generate.assert_not_called()


class TestOnDemandGenerationIsPlanGated:
    def test_free_plan_blocked_with_403(self, db):
        user_id = uuid.uuid4()
        _set_plan(db, user_id, "free")
        content_id = _make_digest(db, user_id)

        with pytest.raises(HTTPException) as exc_info:
            generate_idea_for_trend({"content_id": str(content_id), "cluster_index": 1})

        assert exc_info.value.status_code == 403
        assert "Pro" in exc_info.value.detail

    def test_missing_user_profile_defaults_to_free_and_is_blocked(self, db):
        # No UserProfile row at all (e.g. never finished onboarding) must
        # default to free, not silently allow the pro path.
        user_id = uuid.uuid4()
        content_id = _make_digest(db, user_id)

        with pytest.raises(HTTPException) as exc_info:
            generate_idea_for_trend({"content_id": str(content_id), "cluster_index": 1})

        assert exc_info.value.status_code == 403

    def test_pro_plan_proceeds_to_generation(self, db, mocker):
        mocker.patch(
            "app.pipeline.nodes.content_strategist._generate_ideas_for_clusters",
            return_value=[{"hook": "new hook", "caption": "c", "cta": "cta"}],
        )
        mocker.patch(
            "app.pipeline.nodes.trend_validator._validate_ideas_via_llm",
            return_value=[{"safe": True, "coherent": True, "specific": True}],
        )
        user_id = uuid.uuid4()
        _set_plan(db, user_id, "pro")
        content_id = _make_digest(db, user_id)

        result = generate_idea_for_trend({"content_id": str(content_id), "cluster_index": 1})

        assert result["hook"] == "new hook"
        assert result["source"] == "on_demand"

    def test_superadmin_bypasses_the_gate_even_on_free_plan(self, db, mocker, monkeypatch):
        mocker.patch(
            "app.pipeline.nodes.content_strategist._generate_ideas_for_clusters",
            return_value=[{"hook": "admin hook", "caption": "c", "cta": "cta"}],
        )
        mocker.patch(
            "app.pipeline.nodes.trend_validator._validate_ideas_via_llm",
            return_value=[{"safe": True, "coherent": True, "specific": True}],
        )
        user_id = uuid.uuid4()
        monkeypatch.setenv("SUPERADMIN_USER_ID", str(user_id))
        _set_plan(db, user_id, "free")
        content_id = _make_digest(db, user_id)

        result = generate_idea_for_trend({"content_id": str(content_id), "cluster_index": 1})

        assert result["hook"] == "admin hook"
