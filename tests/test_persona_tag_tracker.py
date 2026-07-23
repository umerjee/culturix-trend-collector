from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.persona import Persona
from app.models.persona_occurrence import PersonaOccurrence
from app.pipeline.nodes.persona_tag_tracker import (
    map_persona_tags,
    _recompute_status_and_momentum,
    _PROMOTION_MIN_OCCURRENCES,
)


@pytest.fixture
def tracker_db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Persona.__table__, PersonaOccurrence.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _mint_persona(session, **overrides):
    defaults = dict(
        name="Cottagecore", description="rural aesthetic", motivations="calm",
        interests="baking", centroid_embedding=[1.0, 0.0, 0.0], status="pending",
        occurrence_count=1, first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    persona = Persona(**defaults)
    session.add(persona)
    session.commit()
    return persona


class TestMapPersonaTags:
    def test_empty_clusters_short_circuits(self, mocker, tracker_db):
        mock_embed = mocker.patch("app.embeddings.embed_batch")
        state = {"clusters": []}
        result = map_persona_tags(state)
        assert result["clusters"] == []
        mock_embed.assert_not_called()

    def test_no_match_mints_new_pending_persona_with_first_occurrence(self, mocker, tracker_db):
        mocker.patch(
            "app.pipeline.nodes.persona_tag_tracker._infer_persona_from_cluster",
            return_value={"name": "Cottagecore", "description": "rural aesthetic", "motivations": "calm", "interests": "baking"},
        )
        state = {"clusters": [{"name": "Farmhouse vibes", "description": "rustic living", "_embedding": [1.0, 0.0, 0.0]}]}

        map_persona_tags(state)

        session = tracker_db()
        try:
            personas = session.query(Persona).all()
            assert len(personas) == 1
            assert personas[0].name == "Cottagecore"
            assert personas[0].status == "pending"
            assert personas[0].occurrence_count == 1
            assert session.query(PersonaOccurrence).filter_by(persona_id=personas[0].id).count() == 1
        finally:
            session.close()

    def test_matching_cluster_logs_occurrence_on_existing_persona_instead_of_minting(self, mocker, tracker_db):
        session = tracker_db()
        persona = _mint_persona(session, occurrence_count=1)
        persona_id = persona.id
        session.close()

        mock_infer = mocker.patch("app.pipeline.nodes.persona_tag_tracker._infer_persona_from_cluster")
        state = {"clusters": [{"name": "Cottagecore aesthetic", "description": "rural life", "_embedding": [0.99, 0.01, 0.0]}]}

        map_persona_tags(state)

        mock_infer.assert_not_called()
        session = tracker_db()
        try:
            assert session.query(Persona).count() == 1
            updated = session.query(Persona).filter_by(id=persona_id).first()
            assert updated.occurrence_count == 2
            assert session.query(PersonaOccurrence).filter_by(persona_id=persona_id).count() == 1
        finally:
            session.close()

    def test_same_day_rerun_does_not_duplicate_occurrence(self, mocker, tracker_db):
        session = tracker_db()
        persona = _mint_persona(session, occurrence_count=1)
        persona_id = persona.id
        session.add(PersonaOccurrence(persona_id=persona_id, occurrence_date=date.today(), day_of_week=date.today().weekday()))
        session.commit()
        session.close()

        state = {"clusters": [{"name": "Cottagecore", "description": "rural aesthetic", "_embedding": [1.0, 0.0, 0.0]}]}
        map_persona_tags(state)

        session = tracker_db()
        try:
            assert session.query(PersonaOccurrence).filter_by(persona_id=persona_id).count() == 1
            assert session.query(Persona).filter_by(id=persona_id).first().occurrence_count == 1
        finally:
            session.close()

    def test_recomputes_promotion_after_third_occurrence(self, mocker, tracker_db):
        session = tracker_db()
        _mint_persona(session, occurrence_count=_PROMOTION_MIN_OCCURRENCES - 1, status="pending")
        session.close()

        mocker.patch("app.pipeline.nodes.persona_tag_tracker._infer_persona_from_cluster")
        state = {"clusters": [{"name": "Cottagecore", "description": "rural aesthetic", "_embedding": [1.0, 0.0, 0.0]}]}
        map_persona_tags(state)

        session = tracker_db()
        try:
            persona = session.query(Persona).first()
            assert persona.occurrence_count == _PROMOTION_MIN_OCCURRENCES
            assert persona.status == "active"
        finally:
            session.close()


class TestRecomputeStatusAndMomentum:
    def test_pending_promotes_at_threshold(self, tracker_db):
        session = tracker_db()
        persona = _mint_persona(session, status="pending", occurrence_count=_PROMOTION_MIN_OCCURRENCES)
        _recompute_status_and_momentum(session, persona)
        assert persona.status == "active"

    def test_pending_expires_to_dormant_after_window_without_promotion(self, tracker_db):
        session = tracker_db()
        persona = _mint_persona(
            session, status="pending", occurrence_count=1,
            first_seen_at=datetime.utcnow() - timedelta(days=15),
        )
        _recompute_status_and_momentum(session, persona)
        assert persona.status == "dormant"

    def test_pending_still_within_window_stays_pending(self, tracker_db):
        session = tracker_db()
        persona = _mint_persona(
            session, status="pending", occurrence_count=1,
            first_seen_at=datetime.utcnow() - timedelta(days=5),
        )
        _recompute_status_and_momentum(session, persona)
        assert persona.status == "pending"

    def test_active_goes_dormant_after_long_silence(self, tracker_db):
        session = tracker_db()
        persona = _mint_persona(
            session, status="active", occurrence_count=5,
            last_seen_at=datetime.utcnow() - timedelta(days=50),
        )
        _recompute_status_and_momentum(session, persona)
        assert persona.status == "dormant"
        assert persona.momentum is None

    def test_active_momentum_up_when_recent_occurrences_outpace_prior(self, tracker_db):
        session = tracker_db()
        persona = _mint_persona(session, status="active", last_seen_at=datetime.utcnow())
        today = date.today()
        # Prior window (15-28 days ago): 2 occurrences (baseline)
        for offset in (16, 20):
            session.add(PersonaOccurrence(persona_id=persona.id, occurrence_date=today - timedelta(days=offset), day_of_week=0))
        # Recent window (0-14 days ago): 4 occurrences — clearly rising
        for offset in (1, 3, 5, 7):
            session.add(PersonaOccurrence(persona_id=persona.id, occurrence_date=today - timedelta(days=offset), day_of_week=0))
        session.commit()

        _recompute_status_and_momentum(session, persona)
        assert persona.momentum == "up"

    def test_active_momentum_down_when_recent_occurrences_drop(self, tracker_db):
        session = tracker_db()
        persona = _mint_persona(session, status="active", last_seen_at=datetime.utcnow())
        today = date.today()
        for offset in (16, 18, 20, 22):
            session.add(PersonaOccurrence(persona_id=persona.id, occurrence_date=today - timedelta(days=offset), day_of_week=0))
        for offset in (1,):
            session.add(PersonaOccurrence(persona_id=persona.id, occurrence_date=today - timedelta(days=offset), day_of_week=0))
        session.commit()

        _recompute_status_and_momentum(session, persona)
        assert persona.momentum == "down"

    def test_active_momentum_none_without_prior_baseline(self, tracker_db):
        session = tracker_db()
        persona = _mint_persona(session, status="active", last_seen_at=datetime.utcnow())
        today = date.today()
        session.add(PersonaOccurrence(persona_id=persona.id, occurrence_date=today - timedelta(days=1), day_of_week=0))
        session.commit()

        _recompute_status_and_momentum(session, persona)
        assert persona.momentum is None
