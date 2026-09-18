"""Tests for app/routers/world.py — the public, unauthenticated read surface
for World Features (subject-centric public content). Every query here must
stay pre-filtered to is_world_content=True AND status='ready' with a real
video — no ordinary user's private Toons should ever be reachable through
this router.
"""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.toon import Toon
from app.models.toon_script import ToonScript
from app.routers import world


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Toon.__table__, ToonScript.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_toon(db, *, is_world_content=True, status="ready", final_video_url="https://cdn/x.mp4",
               subject_region="IR", subject_text="The Strait of Hormuz", subject_category="place",
               title="The Strait of Hormuz", hook_line="A vital chokepoint."):
    session = db()
    script = ToonScript(brand_id=uuid.uuid4(), hook_line=hook_line, generation_source="ai", status="approved")
    session.add(script)
    session.commit()
    session.refresh(script)
    toon = Toon(
        brand_id=uuid.uuid4(), script_id=script.id, title=title, status=status,
        final_video_url=final_video_url, is_world_content=is_world_content,
        subject_region=subject_region, subject_text=subject_text, subject_category=subject_category,
    )
    session.add(toon)
    session.commit()
    session.refresh(toon)
    toon_id = str(toon.id)
    session.close()
    return toon_id


class TestListWorldFeatures:
    def test_only_ready_world_content_with_a_video_is_returned(self, db):
        _make_toon(db)  # ready, world, has video — should appear
        _make_toon(db, is_world_content=False)  # ordinary user toon — must NOT appear
        _make_toon(db, status="animating")  # not ready yet — must NOT appear
        _make_toon(db, final_video_url=None)  # no video yet — must NOT appear

        result = world.list_world_features()
        assert result["total"] == 1
        assert len(result["features"]) == 1
        assert result["features"][0]["subject_text"] == "The Strait of Hormuz"

    def test_filters_by_region_and_category(self, db):
        _make_toon(db, subject_region="IR", subject_category="place")
        _make_toon(db, subject_region="JP", subject_category="species", subject_text="Deep-sea creatures")

        by_region = world.list_world_features(region="jp")  # lowercase input, stored uppercase
        assert len(by_region["features"]) == 1
        assert by_region["features"][0]["subject_region"] == "JP"

        by_category = world.list_world_features(category="place")
        assert len(by_category["features"]) == 1
        assert by_category["features"][0]["subject_category"] == "place"

    def test_search_matches_subject_text(self, db):
        _make_toon(db, subject_text="The Strait of Hormuz")
        _make_toon(db, subject_text="Mount Fuji")

        result = world.list_world_features(q="fuji")
        assert len(result["features"]) == 1
        assert result["features"][0]["subject_text"] == "Mount Fuji"


class TestListWorldRegions:
    def test_counts_only_ready_world_content(self, db):
        _make_toon(db, subject_region="IR")
        _make_toon(db, subject_region="IR")
        _make_toon(db, subject_region="JP", is_world_content=False)  # must not count

        result = world.list_world_regions()
        regions = {r["region"]: r["count"] for r in result["regions"]}
        assert regions == {"IR": 2}


class TestGetWorldFeature:
    def test_returns_feature_with_hook_line(self, db):
        toon_id = _make_toon(db, hook_line="A vital global oil chokepoint.")
        result = world.get_world_feature(toon_id)
        assert result["subject_text"] == "The Strait of Hormuz"
        assert result["hook_line"] == "A vital global oil chokepoint."

    def test_404s_for_a_non_ready_toon(self, db):
        toon_id = _make_toon(db, status="animating")
        with pytest.raises(HTTPException) as exc_info:
            world.get_world_feature(toon_id)
        assert exc_info.value.status_code == 404

    def test_404s_for_a_private_toon(self, db):
        toon_id = _make_toon(db, is_world_content=False)
        with pytest.raises(HTTPException) as exc_info:
            world.get_world_feature(toon_id)
        assert exc_info.value.status_code == 404

    def test_404s_for_an_invalid_id(self, db):
        with pytest.raises(HTTPException) as exc_info:
            world.get_world_feature("not-a-uuid")
        assert exc_info.value.status_code == 404
