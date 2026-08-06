"""Tests for app/services/culturetoon_usage.py — generation cost tracking
and budget enforcement. In-memory SQLite, no external calls to mock (this
module is pure DB + arithmetic)."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.character_brand import CharacterBrand
from app.models.generation_usage import GenerationUsage
from app.services.culturetoon_usage import (
    record_usage, get_spend, check_budget, estimate_video_cost, estimate_voice_cost,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[CharacterBrand.__table__, GenerationUsage.__table__])
    return sessionmaker(bind=engine)


@pytest.fixture
def brand(db):
    session = db()
    user_id = uuid.uuid4()
    brand = CharacterBrand(user_id=user_id, name="Test Brand")
    session.add(brand)
    session.commit()
    session.refresh(brand)
    session.close()
    return brand


class TestEstimators:
    def test_estimate_video_cost_scales_with_duration(self):
        assert estimate_video_cost(15) == Decimal("1.2600")
        assert estimate_video_cost(5) == Decimal("0.4200")

    def test_estimate_voice_cost_scales_with_char_count(self):
        assert estimate_voice_cost(1000) == Decimal("0.0300")


class TestRecordUsageAndGetSpend:
    def test_record_and_sum(self, db, brand):
        session = db()
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="kling_omni",
                      generation_type="video", cost_usd=Decimal("1.50"))
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="hybrid_image",
                      generation_type="character_image", cost_usd=Decimal("0.50"))
        session.commit()

        spend = get_spend(session, brand.id, datetime.utcnow() - timedelta(days=1))
        assert spend == Decimal("2.00")
        session.close()

    def test_null_cost_not_treated_as_zero_but_not_summed_either(self, db, brand):
        # A not-yet-priced generation (e.g. Qwen-Image fallback) records
        # cost_usd=None — SQL SUM skips NULLs, so it's silently excluded
        # from the total rather than counted as $0. This test documents
        # that behavior explicitly since it's easy to misread as "free."
        session = db()
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="hybrid_image",
                      generation_type="character_image", cost_usd=None)
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="kling_omni",
                      generation_type="video", cost_usd=Decimal("1.00"))
        session.commit()

        spend = get_spend(session, brand.id, datetime.utcnow() - timedelta(days=1))
        assert spend == Decimal("1.00")
        session.close()

    def test_other_brands_not_included(self, db, brand):
        session = db()
        other_brand_id = uuid.uuid4()
        record_usage(session, user_id=brand.user_id, brand_id=other_brand_id, provider="kling_omni",
                      generation_type="video", cost_usd=Decimal("99.00"))
        session.commit()

        spend = get_spend(session, brand.id, datetime.utcnow() - timedelta(days=1))
        assert spend == Decimal("0")
        session.close()


class TestCheckBudget:
    def test_no_budget_set_never_blocks_or_warns(self, db, brand):
        session = db()
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="kling_omni",
                      generation_type="video", cost_usd=Decimal("1000.00"))
        session.commit()

        result = check_budget(session, brand)
        assert result["blocked"] is False
        assert result["warning"] is None
        session.close()

    def test_warns_at_80_percent(self, db, brand):
        brand.monthly_budget = Decimal("100.00")
        session = db()
        session.add(brand)
        session.merge(brand)
        session.commit()
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="kling_omni",
                      generation_type="video", cost_usd=Decimal("85.00"))
        session.commit()

        result = check_budget(session, brand)
        assert result["blocked"] is False
        assert result["warning"] is not None
        assert "80%" in result["warning"] or "85%" in result["warning"]
        session.close()

    def test_blocks_at_100_percent(self, db, brand):
        brand.monthly_budget = Decimal("100.00")
        session = db()
        session.merge(brand)
        session.commit()
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="kling_omni",
                      generation_type="video", cost_usd=Decimal("100.00"))
        session.commit()

        result = check_budget(session, brand)
        assert result["blocked"] is True
        assert "budget exceeded" in result["reason"].lower()
        session.close()

    def test_daily_and_monthly_are_independent(self, db, brand):
        # A brand with only a monthly budget set shouldn't have its daily
        # spend checked against anything (daily_budget is None -> skipped).
        brand.daily_budget = None
        brand.monthly_budget = Decimal("50.00")
        session = db()
        session.merge(brand)
        session.commit()
        record_usage(session, user_id=brand.user_id, brand_id=brand.id, provider="kling_omni",
                      generation_type="video", cost_usd=Decimal("10.00"))
        session.commit()

        result = check_budget(session, brand)
        assert result["blocked"] is False
        assert result["daily_spend"] == Decimal("0")  # not evaluated, no daily_budget set
        session.close()
