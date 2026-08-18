"""Tests for run_culturetoon_trend_dispatch (app/scheduler.py) and
select_trend_for_brand (app/services/culturetoon_script.py) — CultureToons'
scheduled trend-to-script auto-drafting. Mirrors tests/test_digest_dispatch.py's
cadence-gating test shape and tests/test_culturetoons.py's in-memory-SQLite +
direct-router-function fixture convention (avoids importing app.main)."""
import json
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character_brand import CharacterBrand
from app.models.character import Character
from app.models.character_variant import CharacterVariant
from app.models.expression import Expression
from app.models.toon_background import ToonBackground
from app.models.toon_script import ToonScript
from app.models.toon import Toon
from app.models.toon_post import ToonPost
from app.models.toon_episode import ToonEpisode
from app.models.connected_account import ConnectedAccount
from app.models.persona import Persona
from app.models.cluster import Cluster
from app.models.character_relationship import CharacterRelationship
from app.models.character_relationship_event import CharacterRelationshipEvent
from app.models.character_relationship_direction import CharacterRelationshipDirection
from app.models.character_relationship_behavior_rule import CharacterRelationshipBehaviorRule
from app.models.generation_usage import GenerationUsage
from app.models.character_memory import CharacterMemory
from app.models.culture import Culture
from app.models.toon_scene import ToonScene
from app.models.toon_shot import ToonShot
from app.routers import culturetoons
from app.scheduler import run_culturetoon_trend_dispatch
from app.services.culturetoon_script import select_trend_for_brand

# A fixed Wednesday (weekday()==2), same convention as test_digest_dispatch.py.
_WEDNESDAY_NOON = datetime(2026, 7, 22, 12, 0, 0)
assert _WEDNESDAY_NOON.weekday() == 2


@pytest.fixture(autouse=True)
def _no_real_memory_retrieval(mocker):
    return mocker.patch("app.services.culturetoon_memory.retrieve_relevant_memories", return_value=[])


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        CharacterBrand.__table__, Character.__table__, CharacterVariant.__table__,
        Expression.__table__, ToonBackground.__table__, ToonScript.__table__,
        Toon.__table__, ToonPost.__table__, ToonEpisode.__table__, ConnectedAccount.__table__,
        Persona.__table__, Cluster.__table__,
        CharacterRelationship.__table__, GenerationUsage.__table__, CharacterMemory.__table__,
        Culture.__table__, ToonScene.__table__, CharacterRelationshipEvent.__table__,
        CharacterRelationshipDirection.__table__, CharacterRelationshipBehaviorRule.__table__,
        ToonShot.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


@pytest.fixture
def user_id():
    return str(uuid.uuid4())


def _make_brand(db, user_id, **overrides):
    # create_brand doesn't accept delivery_freq/delivery_time/delivery_day_of_week
    # at creation time (see app/routers/culturetoons.py) — set via the same
    # PUT /brands/{id} fields the settings UI already writes to.
    defaults = dict(delivery_freq="daily", delivery_time="09:00", delivery_day_of_week=0)
    defaults.update(overrides)
    brand = culturetoons.create_brand({"user_id": user_id, "name": "Test Brand"})
    return culturetoons.update_brand(brand["id"], {"user_id": user_id, **defaults})


def _make_variant(db, user_id, brand_id, name="Kumar"):
    character = culturetoons.create_character({"user_id": user_id, "brand_id": brand_id, "name": name})
    return culturetoons.create_variant({
        "user_id": user_id, "brand_id": brand_id, "character_id": character["id"], "name": name,
    })


def _make_persona(db, **overrides):
    defaults = dict(name="Persona A", description="desc", status="active")
    defaults.update(overrides)
    session = db()
    try:
        p = Persona(**defaults)
        session.add(p)
        session.commit()
        session.refresh(p)
        return p.id
    finally:
        session.close()


def _mock_qwen_script_response(mocker, hook_line="A funny hook"):
    fake_message = mocker.Mock()
    fake_message.content = json.dumps({
        "hook_line": hook_line,
        "shots": [
            {"shot_number": 1, "duration_seconds": 4, "action": "reacts", "expression": "Shocked", "dialogue": "Wait, what?"},
            {"shot_number": 2, "duration_seconds": 4, "action": "laughs", "expression": "Laughing", "dialogue": None},
        ],
    })
    fake_choice = mocker.Mock()
    fake_choice.message = fake_message
    fake_response = mocker.Mock()
    fake_response.choices = [fake_choice]
    fake_client = mocker.Mock()
    fake_client.chat.completions.create.return_value = fake_response
    os.environ["QWEN_API_KEY"] = "test-key"
    mocker.patch("app.services.culturetoon_script._get_qwen_client", return_value=fake_client)
    return fake_client


class TestRunCultureToonTrendDispatch:
    def test_due_brand_drafts_a_script(self, db, user_id, mocker):
        _mock_qwen_script_response(mocker)
        brand = _make_brand(db, user_id, delivery_time="09:00")
        _make_variant(db, user_id, brand["id"])
        _make_persona(db)

        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON)  # 12:00, past the 09:00 delivery_time

        session = db()
        scripts = session.query(ToonScript).filter_by(brand_id=uuid.UUID(brand["id"])).all()
        session.close()
        assert len(scripts) == 1
        assert scripts[0].generation_source == "ai_auto"
        assert scripts[0].status == "draft"
        assert scripts[0].source_type == "persona"

    def test_skipped_before_delivery_time(self, db, user_id, mocker):
        mock_call = _mock_qwen_script_response(mocker)
        brand = _make_brand(db, user_id, delivery_time="18:00")
        _make_variant(db, user_id, brand["id"])
        _make_persona(db)

        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON)  # 12:00, before 18:00

        mock_call.chat.completions.create.assert_not_called()

    def test_weekly_brand_skipped_on_wrong_weekday(self, db, user_id, mocker):
        mock_call = _mock_qwen_script_response(mocker)
        brand = _make_brand(db, user_id, delivery_freq="weekly", delivery_day_of_week=0, delivery_time="09:00")
        _make_variant(db, user_id, brand["id"])
        _make_persona(db)

        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON)  # Wednesday (2), brand wants Monday (0)

        mock_call.chat.completions.create.assert_not_called()

    def test_brand_with_no_characters_is_skipped(self, db, user_id, mocker):
        mock_call = _mock_qwen_script_response(mocker)
        _make_brand(db, user_id, delivery_time="09:00")
        _make_persona(db)

        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON)

        mock_call.chat.completions.create.assert_not_called()

    def test_brand_with_no_trends_is_skipped(self, db, user_id, mocker):
        mock_call = _mock_qwen_script_response(mocker)
        brand = _make_brand(db, user_id, delivery_time="09:00")
        _make_variant(db, user_id, brand["id"])

        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON)

        mock_call.chat.completions.create.assert_not_called()

    def test_idempotent_within_the_same_day(self, db, user_id, mocker):
        _mock_qwen_script_response(mocker)
        brand = _make_brand(db, user_id, delivery_time="09:00")
        _make_variant(db, user_id, brand["id"])
        _make_persona(db)

        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON)
        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON.replace(hour=13))  # same day, later run

        session = db()
        count = session.query(ToonScript).filter_by(brand_id=uuid.UUID(brand["id"])).count()
        session.close()
        assert count == 1

    def test_one_brand_failing_does_not_block_another(self, db, user_id, mocker):
        _mock_qwen_script_response(mocker)
        brand_fail = _make_brand(db, user_id, delivery_time="09:00")
        _make_variant(db, user_id, brand_fail["id"])
        other_user = str(uuid.uuid4())
        brand_ok = _make_brand(db, other_user, delivery_time="09:00")
        _make_variant(db, other_user, brand_ok["id"])
        _make_persona(db)

        # Force an unexpected (non-ToonScriptGenerationError) exception for
        # brand_fail specifically, while brand_ok goes through the real
        # implementation — exercises run_culturetoon_trend_dispatch's
        # per-brand try/except, not just the narrower
        # ToonScriptGenerationError handling around the LLM call itself.
        from app.routers import culturetoons as culturetoons_router
        real_gather = culturetoons_router._gather_script_generation_context

        def _maybe_blow_up(session, brand_id, variants, query_text=""):
            if str(brand_id) == brand_fail["id"]:
                raise RuntimeError("simulated failure for brand_fail")
            return real_gather(session, brand_id, variants, query_text)

        mocker.patch.object(culturetoons_router, "_gather_script_generation_context", side_effect=_maybe_blow_up)

        run_culturetoon_trend_dispatch(now=_WEDNESDAY_NOON)

        session = db()
        fail_count = session.query(ToonScript).filter_by(brand_id=uuid.UUID(brand_fail["id"])).count()
        ok_count = session.query(ToonScript).filter_by(brand_id=uuid.UUID(brand_ok["id"])).count()
        session.close()
        assert fail_count == 0
        assert ok_count == 1


class TestSelectTrendForBrand:
    def test_no_candidates_returns_none(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id, "name": "Empty"})
        session = db()
        try:
            brand_row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
            assert select_trend_for_brand(session, brand_row) is None
        finally:
            session.close()

    def test_dedups_against_recent_scripts_for_this_brand(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id, "name": "Test"})
        persona_id = _make_persona(db, name="Used Persona")
        session = db()
        try:
            brand_row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
            # A script already exists for this persona, created today.
            session.add(ToonScript(
                brand_id=brand_row.id, source_type="persona", source_id=persona_id,
                generation_source="ai_auto", status="draft",
            ))
            session.commit()

            result = select_trend_for_brand(session, brand_row)
            # Only candidate is already used within the lookback window, so
            # it's returned anyway as the "repeat is better than nothing" fallback.
            assert result is not None
            assert result[0] == "persona" and result[1] == persona_id
        finally:
            session.close()

    def test_unused_persona_is_preferred_over_used_one(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id, "name": "Test"})
        used_id = _make_persona(db, name="Used")
        fresh_id = _make_persona(db, name="Fresh")
        session = db()
        try:
            brand_row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
            session.add(ToonScript(
                brand_id=brand_row.id, source_type="persona", source_id=used_id,
                generation_source="ai_auto", status="draft",
            ))
            session.commit()

            source_type, source_id, _ = select_trend_for_brand(session, brand_row)
            assert (source_type, source_id) == ("persona", fresh_id)
        finally:
            session.close()

    def test_old_script_outside_lookback_window_does_not_count_as_used(self, db, user_id):
        brand = culturetoons.create_brand({"user_id": user_id, "name": "Test"})
        persona_id = _make_persona(db, name="Old news")
        session = db()
        try:
            brand_row = session.query(CharacterBrand).filter_by(id=uuid.UUID(brand["id"])).first()
            old_script = ToonScript(
                brand_id=brand_row.id, source_type="persona", source_id=persona_id,
                generation_source="ai_auto", status="archived",
            )
            session.add(old_script)
            session.commit()
            # Push created_at well outside the 14-day lookback window.
            old_script.created_at = datetime.utcnow() - timedelta(days=30)
            session.commit()

            source_type, source_id, _ = select_trend_for_brand(session, brand_row)
            assert (source_type, source_id) == ("persona", persona_id)
        finally:
            session.close()
