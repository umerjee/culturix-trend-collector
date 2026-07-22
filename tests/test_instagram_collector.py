from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.trend import Trend
from app.collectors.instagram import (
    fetch_instagram_hashtag,
    _cache_instagram_media,
    _parse_taken_at,
    store_instagram_trends,
)

_REAL_ITEM = {
    "id": "3944788094523612966",
    "shortcode": "Da-s98gRR8m",
    "taken_at": "2026-07-19T15:38:41.000Z",
    "caption": "how to dress chic but not boring #ootd #fashion",
    "like_count": 753,
    "comment_count": 17,
    "video_view_count": 0,
    "display_url": "https://scontent.cdninstagram.com/photo.jpg",
    "owner": {"username": "noellecrooks"},
    "url": "https://www.instagram.com/reel/Da-s98gRR8m/",
}


class TestFetchInstagramHashtag:
    def test_extracts_posts_list(self, mocker):
        resp = mocker.Mock(status_code=200)
        resp.json.return_value = {"posts": [_REAL_ITEM], "cursor": None}
        resp.raise_for_status = mocker.Mock()
        mocker.patch("app.collectors.instagram.httpx.get", return_value=resp)

        items = fetch_instagram_hashtag("fashion", api_key="test-key")

        assert items == [_REAL_ITEM]

    def test_paginates_via_cursor_until_exhausted(self, mocker):
        page1 = mocker.Mock(status_code=200)
        page1.json.return_value = {"posts": [_REAL_ITEM], "cursor": "abc"}
        page1.raise_for_status = mocker.Mock()
        page2 = mocker.Mock(status_code=200)
        page2.json.return_value = {"posts": [], "cursor": None}
        page2.raise_for_status = mocker.Mock()
        mock_get = mocker.patch("app.collectors.instagram.httpx.get", side_effect=[page1, page2])

        items = fetch_instagram_hashtag("fashion", api_key="test-key", max_pages=5)

        assert items == [_REAL_ITEM]
        assert mock_get.call_count == 2

    def test_request_failure_returns_whatever_was_collected_so_far(self, mocker):
        mocker.patch("app.collectors.instagram.httpx.get", side_effect=Exception("network error"))
        items = fetch_instagram_hashtag("fashion", api_key="test-key")
        assert items == []


class TestParseTakenAt:
    def test_parses_iso_string_with_milliseconds(self):
        result = _parse_taken_at({"taken_at": "2026-07-19T15:38:41.000Z"})
        assert result == datetime(2026, 7, 19, 15, 38, 41)

    def test_missing_returns_none(self):
        assert _parse_taken_at({}) is None

    def test_non_string_returns_none(self):
        assert _parse_taken_at({"taken_at": 12345}) is None


class TestCacheInstagramMedia:
    def test_downloads_and_uploads_display_url(self, mocker):
        img_resp = mocker.Mock(status_code=200, content=b"fake-bytes")
        img_resp.raise_for_status = mocker.Mock()
        mocker.patch("app.collectors.instagram.httpx.get", return_value=img_resp)
        mock_upload = mocker.patch("app.media.storage.upload", return_value="https://cdn.example.com/cached.jpg")

        result = _cache_instagram_media(_REAL_ITEM, "ext123")

        assert result == "https://cdn.example.com/cached.jpg"
        mock_upload.assert_called_once()
        assert mock_upload.call_args.args[1] == "trend-thumbnails/instagram/ext123.jpg"

    def test_no_media_url_returns_none(self):
        assert _cache_instagram_media({}, "ext123") is None

    def test_download_failure_fails_open_to_none(self, mocker):
        mocker.patch("app.collectors.instagram.httpx.get", side_effect=Exception("boom"))
        assert _cache_instagram_media(_REAL_ITEM, "ext123") is None


@pytest.fixture
def instagram_db(mocker):
    """app/collectors/instagram.py does `from app.db import SessionLocal` at
    module load time (matching tiktok.py/youtube.py's existing style), so the
    mock must target the name bound in THIS module's namespace, not
    app.db.SessionLocal itself — patching the latter would silently leave
    every collector call hitting the real production database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Trend.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.collectors.instagram.SessionLocal", TestSessionLocal)
    return TestSessionLocal


class TestStoreInstagramTrends:
    def test_no_api_key_returns_zero_without_querying(self, instagram_db, monkeypatch):
        monkeypatch.delenv("SCRAPE_CREATORS_API_KEY", raising=False)
        assert store_instagram_trends() == 0

    def test_inserts_valid_item_with_expected_fields(self, instagram_db, monkeypatch, mocker):
        monkeypatch.setenv("SCRAPE_CREATORS_API_KEY", "test-key")
        mocker.patch("app.collectors.instagram.fetch_instagram_hashtag", return_value=[_REAL_ITEM])
        mocker.patch("app.collectors.instagram._cache_instagram_media", return_value="https://cdn.example.com/cached.jpg")

        inserted = store_instagram_trends(hashtags=["fashion"])

        assert inserted == 1
        session = instagram_db()
        trend = session.query(Trend).filter_by(platform="instagram", external_id="3944788094523612966").first()
        assert trend.author == "noellecrooks"
        assert trend.likes == 753
        assert trend.region is None
        assert trend.image_url == "https://cdn.example.com/cached.jpg"
        session.close()

    def test_item_missing_id_is_skipped(self, instagram_db, monkeypatch, mocker):
        monkeypatch.setenv("SCRAPE_CREATORS_API_KEY", "test-key")
        item = {**_REAL_ITEM, "id": None, "shortcode": None}
        mocker.patch("app.collectors.instagram.fetch_instagram_hashtag", return_value=[item])

        assert store_instagram_trends(hashtags=["fashion"]) == 0

    def test_item_missing_taken_at_is_skipped(self, instagram_db, monkeypatch, mocker):
        monkeypatch.setenv("SCRAPE_CREATORS_API_KEY", "test-key")
        item = {**_REAL_ITEM, "taken_at": None}
        mocker.patch("app.collectors.instagram.fetch_instagram_hashtag", return_value=[item])

        assert store_instagram_trends(hashtags=["fashion"]) == 0

    def test_duplicate_across_hashtags_is_deduped_within_run(self, instagram_db, monkeypatch, mocker):
        monkeypatch.setenv("SCRAPE_CREATORS_API_KEY", "test-key")
        mocker.patch("app.collectors.instagram.fetch_instagram_hashtag", return_value=[_REAL_ITEM])
        mocker.patch("app.collectors.instagram._cache_instagram_media", return_value=None)

        inserted = store_instagram_trends(hashtags=["fashion", "viral"])

        assert inserted == 1

    def test_already_existing_external_id_is_skipped(self, instagram_db, monkeypatch, mocker):
        monkeypatch.setenv("SCRAPE_CREATORS_API_KEY", "test-key")
        session = instagram_db()
        session.add(Trend(platform="instagram", external_id="3944788094523612966"))
        session.commit()
        session.close()

        mocker.patch("app.collectors.instagram.fetch_instagram_hashtag", return_value=[_REAL_ITEM])

        assert store_instagram_trends(hashtags=["fashion"]) == 0
