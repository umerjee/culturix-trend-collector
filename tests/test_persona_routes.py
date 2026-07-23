import uuid
from datetime import datetime, date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.content_profile import ContentProfile
from app.models.persona import Persona
from app.models.persona_occurrence import PersonaOccurrence
from app.main import list_active_personas, persona_advisory, persona_occurrences


@pytest.fixture
def db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[
        ContentProfile.__table__, Persona.__table__, PersonaOccurrence.__table__,
    ])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestListActivePersonas:
    def test_only_returns_active_status(self, db):
        session = db()
        session.add(Persona(name="Active One", description="d", status="active", momentum="up"))
        session.add(Persona(name="Still Pending", description="d", status="pending"))
        session.add(Persona(name="Gone Dormant", description="d", status="dormant"))
        session.commit()
        session.close()

        result = list_active_personas()

        assert [p["name"] for p in result] == ["Active One"]
        assert result[0]["momentum"] == "up"


class TestPersonaAdvisory:
    def test_profile_not_found_404s(self, db):
        with pytest.raises(HTTPException) as exc:
            persona_advisory(str(uuid.uuid4()), str(uuid.uuid4()))
        assert exc.value.status_code == 404

    def test_no_persona_tags_returns_empty(self, db):
        session = db()
        profile = ContentProfile(user_id=uuid.uuid4(), name="P", persona_tags=[])
        session.add(profile)
        session.commit()
        user_id, profile_id = profile.user_id, profile.id
        session.close()

        result = persona_advisory(str(user_id), str(profile_id))
        assert result == {"declining": [], "dormant": []}

    def test_flags_declining_and_dormant_tags_only(self, db):
        session = db()
        profile = ContentProfile(
            user_id=uuid.uuid4(), name="P",
            persona_tags=["Cottagecore", "Gen Z", "Quiet Luxury"],
        )
        session.add(profile)
        session.add(Persona(name="Cottagecore", description="d", status="active", momentum="down"))
        session.add(Persona(name="Gen Z", description="d", status="dormant"))
        session.add(Persona(name="Quiet Luxury", description="d", status="active", momentum="up"))
        session.commit()
        user_id, profile_id = profile.user_id, profile.id
        session.close()

        result = persona_advisory(str(user_id), str(profile_id))

        assert result["declining"] == [{"name": "Cottagecore"}]
        assert result["dormant"] == [{"name": "Gen Z"}]


class TestPersonaOccurrencesRoute:
    def test_returns_rows_shaped_for_trend_occurrence_interface(self, db):
        session = db()
        persona = Persona(name="Cottagecore", description="d", status="active")
        session.add(persona)
        session.commit()
        session.add(PersonaOccurrence(persona_id=persona.id, occurrence_date=date(2026, 1, 5), day_of_week=0))
        session.commit()
        persona_id = persona.id
        session.close()

        result = persona_occurrences(persona_id)

        assert len(result) == 1
        assert result[0]["occurrence_date"] == "2026-01-05"
        assert result[0]["day_of_week"] == 0
        assert result[0]["size"] is None
        assert result[0]["durability"] is None
