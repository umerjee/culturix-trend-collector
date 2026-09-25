"""Tests for POST /admin/toons/{id}/publish-showcase and .../unpublish-showcase —
Toon.public_showcase's own docstring explains why both an explicit flag AND a matching
character home_region are required before a CultureToons clip can appear on the public
World Feature page's "More from this region" strip."""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.toon import Toon
from app.models.toon_script import ToonScript
from app.models.character import Character
from app.models.character_variant import CharacterVariant
from app import main


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        Toon.__table__, ToonScript.__table__, Character.__table__, CharacterVariant.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _make_variant(db, *, home_region=None):
    session = db()
    character = Character(brand_id=uuid.uuid4(), name="Kumar", home_region=home_region)
    session.add(character)
    session.commit()
    session.refresh(character)
    variant = CharacterVariant(character_id=character.id, name="Kumar")
    session.add(variant)
    session.commit()
    session.refresh(variant)
    variant_id = variant.id
    session.close()
    return variant_id


def _make_toon(db, *, status="ready", final_video_url="https://cdn/x.mp4", character_variant_id=None):
    session = db()
    script = ToonScript(brand_id=uuid.uuid4(), generation_source="ai", status="approved")
    session.add(script)
    session.commit()
    session.refresh(script)
    toon = Toon(brand_id=uuid.uuid4(), script_id=script.id, title="A clip", status=status,
               final_video_url=final_video_url, is_world_content=False,
               character_variant_id=character_variant_id)
    session.add(toon)
    session.commit()
    session.refresh(toon)
    toon_id = str(toon.id)
    session.close()
    return toon_id


class TestPublishToonShowcase:
    def test_a_ready_toon_with_a_home_region_gets_showcased(self, db):
        variant_id = _make_variant(db, home_region="US")
        toon_id = _make_toon(db, character_variant_id=variant_id)

        result = main.publish_toon_showcase(toon_id)

        assert result == {"status": "showcased", "toon_id": toon_id, "home_region": "US"}

    def test_an_unfinished_render_is_rejected(self, db):
        variant_id = _make_variant(db, home_region="US")
        toon_id = _make_toon(db, status="animating", final_video_url=None, character_variant_id=variant_id)

        with pytest.raises(HTTPException) as exc_info:
            main.publish_toon_showcase(toon_id)
        assert exc_info.value.status_code == 409

    def test_a_character_with_no_home_region_is_rejected(self, db):
        variant_id = _make_variant(db, home_region=None)
        toon_id = _make_toon(db, character_variant_id=variant_id)

        with pytest.raises(HTTPException) as exc_info:
            main.publish_toon_showcase(toon_id)
        assert exc_info.value.status_code == 409

    def test_a_toon_with_no_character_at_all_is_rejected(self, db):
        toon_id = _make_toon(db, character_variant_id=None)

        with pytest.raises(HTTPException) as exc_info:
            main.publish_toon_showcase(toon_id)
        assert exc_info.value.status_code == 409

    def test_an_unknown_toon_404s(self, db):
        with pytest.raises(HTTPException) as exc_info:
            main.publish_toon_showcase(str(uuid.uuid4()))
        assert exc_info.value.status_code == 404


class TestUnpublishToonShowcase:
    def test_clears_the_flag(self, db):
        variant_id = _make_variant(db, home_region="US")
        toon_id = _make_toon(db, character_variant_id=variant_id)
        main.publish_toon_showcase(toon_id)

        result = main.unpublish_toon_showcase(toon_id)

        assert result == {"status": "unshowcased", "toon_id": toon_id}

    def test_an_unknown_toon_404s(self, db):
        with pytest.raises(HTTPException) as exc_info:
            main.unpublish_toon_showcase(str(uuid.uuid4()))
        assert exc_info.value.status_code == 404
