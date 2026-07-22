import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.trend import Trend
from app.collectors.twitter import store_twitter_trends


@pytest.fixture
def twitter_db(mocker):
    """app/collectors/twitter.py does `from app.db import SessionLocal`
    INSIDE _store_via_apify/_store_via_proxy (deferred, not module top-level)
    specifically so this mock target — app.db.SessionLocal itself — actually
    takes effect at call time. Patching a module-level name here would be a
    no-op, since no such name exists in this module's namespace."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Trend.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestStoreTwitterTrends:
    def test_apify_success_does_not_fall_back_to_proxy(self, twitter_db, monkeypatch, mocker):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        mocker.patch(
            "app.collectors.twitter._collect_via_apify",
            return_value=[{
                "external_id": "123", "content_text": "trending tweet",
                "author": "someone", "url": "https://x.com/i/web/status/123",
                "likes": 10, "comments": 2, "shares": 1, "views": 100, "language": "en",
            }],
        )
        mock_proxy = mocker.patch("app.collectors.twitter._fetch_via_proxy")

        inserted = store_twitter_trends()

        assert inserted == 1
        mock_proxy.assert_not_called()

    def test_apify_failure_falls_back_to_proxy(self, twitter_db, monkeypatch, mocker):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        mocker.patch("app.collectors.twitter._collect_via_apify", side_effect=Exception("actor down"))
        mocker.patch("app.collectors.twitter._fetch_via_proxy", return_value=["#SomeTrend"])

        inserted = store_twitter_trends(region="global")

        assert inserted >= 1

    def test_apify_returns_nothing_falls_back_to_proxy(self, twitter_db, monkeypatch, mocker):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        mocker.patch("app.collectors.twitter._collect_via_apify", return_value=[])
        mocker.patch("app.collectors.twitter._fetch_via_proxy", return_value=["#AnotherTrend"])

        inserted = store_twitter_trends(region="global")

        assert inserted >= 1

    def test_no_apify_token_goes_straight_to_proxy(self, twitter_db, monkeypatch, mocker):
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        mock_apify = mocker.patch("app.collectors.twitter._collect_via_apify")
        mocker.patch("app.collectors.twitter._fetch_via_proxy", return_value=["#ProxyTrend"])

        inserted = store_twitter_trends(region="global")

        assert inserted >= 1
        mock_apify.assert_not_called()

    def test_proxy_dedupes_across_regions_within_one_run(self, twitter_db, monkeypatch, mocker):
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        mocker.patch("app.collectors.twitter._fetch_via_proxy", return_value=["#SameTrend"])

        inserted = store_twitter_trends(region="global")

        session = twitter_db()
        count = session.query(Trend).filter_by(platform="twitter", external_id="#SameTrend").count()
        session.close()
        assert count == 1
        assert inserted == 1

    def test_proxy_tags_region_via_normalize_region(self, twitter_db, monkeypatch, mocker):
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        mocker.patch("app.collectors.twitter._fetch_via_proxy", return_value=["#UkTrend"])

        store_twitter_trends(region="uk")

        session = twitter_db()
        trend = session.query(Trend).filter_by(platform="twitter", external_id="#UkTrend").first()
        session.close()
        assert trend.region == "GB"

    def test_apify_skips_items_missing_external_id(self, twitter_db, monkeypatch, mocker):
        monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
        mocker.patch(
            "app.collectors.twitter._collect_via_apify",
            return_value=[{"external_id": "", "content_text": "no id"}],
        )
        mocker.patch("app.collectors.twitter._fetch_via_proxy", return_value=[])

        inserted = store_twitter_trends()

        assert inserted == 0
