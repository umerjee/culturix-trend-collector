import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.trend import Trend
from app.collectors.google_trends import fetch_trending, store_google_trends_trends, _approx_traffic_to_int

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:ht="https://trends.google.com/trending/rss" version="2.0">
<channel>
<title>Daily Search Trends</title>
<item>
<title>epic</title>
<ht:approx_traffic>1000+</ht:approx_traffic>
<description/>
<link>https://trends.google.com/trending/rss?geo=US</link>
<pubDate>Tue, 11 Aug 2026 05:30:00 -0700</pubDate>
<ht:picture>https://encrypted-tbn0.gstatic.com/images?q=abc</ht:picture>
<ht:picture_source>Ars Technica</ht:picture_source>
<ht:news_item>
<ht:news_item_title>Following Epic loss, Google has started hosting rival app stores</ht:news_item_title>
<ht:news_item_snippet/>
<ht:news_item_url>https://arstechnica.com/some-article</ht:news_item_url>
<ht:news_item_picture>https://encrypted-tbn0.gstatic.com/images?q=def</ht:news_item_picture>
<ht:news_item_source>Ars Technica</ht:news_item_source>
</ht:news_item>
<ht:news_item>
<ht:news_item_title>Aptoide Returns to Google Play After More Than a Decade</ht:news_item_title>
<ht:news_item_snippet/>
<ht:news_item_url>https://www.prnewswire.com/some-release</ht:news_item_url>
<ht:news_item_picture>https://encrypted-tbn3.gstatic.com/images?q=ghi</ht:news_item_picture>
<ht:news_item_source>PR Newswire</ht:news_item_source>
</ht:news_item>
</item>
<item>
<title>fraud</title>
<ht:approx_traffic>500+</ht:approx_traffic>
<description/>
<link>https://trends.google.com/trending/rss?geo=US</link>
<pubDate>Tue, 11 Aug 2026 05:30:00 -0700</pubDate>
<ht:picture>https://encrypted-tbn1.gstatic.com/images?q=jkl</ht:picture>
<ht:picture_source>Archaeology Magazine</ht:picture_source>
</item>
<item>
<title></title>
<ht:approx_traffic>200+</ht:approx_traffic>
</item>
</channel>
</rss>
"""


class TestFetchTrending:
    def test_parses_titles_traffic_and_news_items(self, mocker):
        mocker.patch("httpx.get", return_value=mocker.Mock(
            status_code=200, content=_SAMPLE_RSS.encode("utf-8"),
            raise_for_status=lambda: None,
        ))

        items = fetch_trending("US")

        assert len(items) == 2  # third item has an empty title, skipped
        assert items[0]["title"] == "epic"
        assert items[0]["traffic"] == "1000+"
        assert items[0]["image_url"] == "https://encrypted-tbn0.gstatic.com/images?q=abc"
        assert len(items[0]["news_items"]) == 2
        assert items[0]["news_items"][0]["title"] == "Following Epic loss, Google has started hosting rival app stores"
        assert items[0]["news_items"][0]["source"] == "Ars Technica"

    def test_item_with_no_news_items_still_parsed(self, mocker):
        mocker.patch("httpx.get", return_value=mocker.Mock(
            status_code=200, content=_SAMPLE_RSS.encode("utf-8"),
            raise_for_status=lambda: None,
        ))

        items = fetch_trending("US")
        assert items[1]["title"] == "fraud"
        assert items[1]["news_items"] == []

    def test_respects_limit(self, mocker):
        mocker.patch("httpx.get", return_value=mocker.Mock(
            status_code=200, content=_SAMPLE_RSS.encode("utf-8"),
            raise_for_status=lambda: None,
        ))

        items = fetch_trending("US", limit=1)
        assert len(items) == 1

    def test_passes_geo_param(self, mocker):
        mock_get = mocker.patch("httpx.get", return_value=mocker.Mock(
            status_code=200, content=_SAMPLE_RSS.encode("utf-8"),
            raise_for_status=lambda: None,
        ))

        fetch_trending("GB")
        assert mock_get.call_args.kwargs["params"] == {"geo": "GB"}

    def test_returns_empty_list_on_request_failure(self, mocker):
        mocker.patch("httpx.get", side_effect=Exception("connection reset"))
        assert fetch_trending("US") == []

    def test_returns_empty_list_on_malformed_xml(self, mocker):
        mocker.patch("httpx.get", return_value=mocker.Mock(
            status_code=200, content=b"not xml at all <<<",
            raise_for_status=lambda: None,
        ))
        assert fetch_trending("US") == []


class TestApproxTrafficToInt:
    def test_parses_plus_suffixed_numbers(self):
        assert _approx_traffic_to_int("1000+") == 1000
        assert _approx_traffic_to_int("500+") == 500

    def test_empty_or_unparsable_returns_zero(self):
        assert _approx_traffic_to_int("") == 0
        assert _approx_traffic_to_int("N/A") == 0


@pytest.fixture
def google_trends_db(mocker):
    """app/collectors/google_trends.py does `from app.db import SessionLocal`
    INSIDE store_google_trends_trends (deferred, not module top-level) so
    this mock target actually takes effect at call time — same pattern as
    test_twitter_collector.py's twitter_db fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Trend.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.db.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestStoreGoogleTrendsTrends:
    def test_inserts_trends_with_normalized_region(self, google_trends_db, mocker):
        mocker.patch(
            "app.collectors.google_trends.fetch_trending",
            return_value=[{
                "title": "epic", "traffic": "1000+", "pub_date": "", "image_url": "https://img/epic.png",
                "news_items": [{"title": "Some news", "url": "https://x.com", "source": "X"}],
            }],
        )

        inserted = store_google_trends_trends(regions=["US"])

        assert inserted == 1
        session = google_trends_db()
        trend = session.query(Trend).filter_by(platform="google_trends").first()
        assert trend.title == "epic"
        assert trend.region == "US"
        assert trend.likes == 1000
        assert trend.language == "en"
        assert trend.image_url == "https://img/epic.png"
        assert "epic" in trend.content
        assert "Some news" in trend.content
        assert trend.translated_content == trend.content
        session.close()

    def test_dedupes_within_same_day(self, google_trends_db, mocker):
        mocker.patch(
            "app.collectors.google_trends.fetch_trending",
            return_value=[{"title": "epic", "traffic": "1000+", "pub_date": "", "image_url": None, "news_items": []}],
        )

        first = store_google_trends_trends(regions=["US"])
        second = store_google_trends_trends(regions=["US"])

        assert first == 1
        assert second == 0  # already exists for today

    def test_multiple_regions_produce_independent_rows(self, google_trends_db, mocker):
        def fake_fetch(region, limit=20):
            return [{"title": f"trend-{region}", "traffic": "500+", "pub_date": "", "image_url": None, "news_items": []}]

        mocker.patch("app.collectors.google_trends.fetch_trending", side_effect=fake_fetch)

        inserted = store_google_trends_trends(regions=["US", "GB"])

        assert inserted == 2
        session = google_trends_db()
        regions = {t.region for t in session.query(Trend).filter_by(platform="google_trends").all()}
        assert regions == {"US", "GB"}
        session.close()

    def test_language_follows_region_map(self, google_trends_db, mocker):
        mocker.patch(
            "app.collectors.google_trends.fetch_trending",
            return_value=[{"title": "epique", "traffic": "500+", "pub_date": "", "image_url": None, "news_items": []}],
        )

        store_google_trends_trends(regions=["FR"])

        session = google_trends_db()
        trend = session.query(Trend).filter_by(platform="google_trends").first()
        assert trend.language == "fr"
        session.close()

    def test_one_region_failing_does_not_block_others(self, google_trends_db, mocker):
        def fake_fetch(region, limit=20):
            if region == "US":
                raise Exception("boom")  # fetch_trending itself always catches, but guard the caller too
            return [{"title": f"trend-{region}", "traffic": "", "pub_date": "", "image_url": None, "news_items": []}]

        # fetch_trending never actually raises (it catches internally), but
        # store_google_trends_trends must still tolerate an empty result for
        # one region without losing the others.
        def safe_fake_fetch(region, limit=20):
            try:
                return fake_fetch(region, limit)
            except Exception:
                return []

        mocker.patch("app.collectors.google_trends.fetch_trending", side_effect=safe_fake_fetch)

        inserted = store_google_trends_trends(regions=["US", "GB"])
        assert inserted == 1

    def test_defaults_to_default_regions_when_none_given(self, google_trends_db, mocker):
        from app.collectors.google_trends import DEFAULT_REGIONS
        mock_fetch = mocker.patch("app.collectors.google_trends.fetch_trending", return_value=[])

        store_google_trends_trends()

        called_regions = [call.args[0] for call in mock_fetch.call_args_list]
        assert called_regions == DEFAULT_REGIONS
