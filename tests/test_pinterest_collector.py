"""Tests for app/collectors/pinterest.py's region loop — store_pinterest_signals
previously always fetched region="US" only, regardless of PINTEREST_REGIONS,
since orchestrator.py calls it with zero args and there was no loop at all
(see that function's own docstring/comment for the real-bug history)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.trend import Trend
from app.collectors.pinterest import store_pinterest_signals, PINTEREST_REGIONS


@pytest.fixture
def pinterest_db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Trend.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestStorePinterestSignals:
    def test_default_region_sweeps_the_full_region_list(self, pinterest_db, mocker):
        def fake_collect(keywords=None, region="US", max_items=25):
            return [{
                "external_id": f"{region}:trend", "content_text": f"{region} trend",
                "likes": 5, "region": region, "raw": {},
            }]

        mock_collect = mocker.patch("app.collectors.pinterest.collect_pinterest", side_effect=fake_collect)

        inserted = store_pinterest_signals()

        assert inserted == len(PINTEREST_REGIONS)
        called_regions = {c.args[1] if len(c.args) > 1 else c.kwargs.get("region") for c in mock_collect.call_args_list}
        assert called_regions == set(PINTEREST_REGIONS)

    def test_explicit_non_us_region_fetches_only_that_one(self, pinterest_db, mocker):
        mock_collect = mocker.patch("app.collectors.pinterest.collect_pinterest", return_value=[])

        store_pinterest_signals(region="TR")

        assert mock_collect.call_count == 1
        assert mock_collect.call_args.args[1] == "TR" or mock_collect.call_args.kwargs.get("region") == "TR"

    def test_dedupes_same_keyword_across_regions(self, pinterest_db, mocker):
        mocker.patch(
            "app.collectors.pinterest.collect_pinterest",
            return_value=[{"external_id": "US:aesthetic", "content_text": "x", "likes": 1, "region": "US", "raw": {}}],
        )

        inserted = store_pinterest_signals()

        session = pinterest_db()
        count = session.query(Trend).filter_by(platform="pinterest", external_id="US:aesthetic").count()
        session.close()
        assert count == 1
        assert inserted == 1
