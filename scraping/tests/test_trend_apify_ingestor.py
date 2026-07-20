import os
from datetime import datetime, timezone

import pytest

from culturix_scraping.collectors.trend_apify_ingestor import (
    _first_int,
    _infer_platform,
    _parse_created_at,
    _resolve_dataset_id,
    _trigger_actor_run,
    map_apify_item,
)


class TestInferPlatform:
    def test_explicit_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("APIFY_PLATFORM", "Instagram")
        assert _infer_platform({"platform": "tiktok"}) == "instagram"

    def test_falls_back_to_item_field(self, monkeypatch):
        monkeypatch.delenv("APIFY_PLATFORM", raising=False)
        assert _infer_platform({"platform": "TikTok"}) == "tiktok"

    def test_falls_back_to_url_host(self, monkeypatch):
        monkeypatch.delenv("APIFY_PLATFORM", raising=False)
        item = {"webVideoUrl": "https://www.tiktok.com/@user/video/123"}
        assert _infer_platform(item) == "tiktok"

    def test_falls_back_to_x_url_host(self, monkeypatch):
        monkeypatch.delenv("APIFY_PLATFORM", raising=False)
        item = {"url": "https://x.com/someuser/status/123"}
        assert _infer_platform(item) == "twitter"

    def test_unrecognized_returns_none(self, monkeypatch):
        monkeypatch.delenv("APIFY_PLATFORM", raising=False)
        assert _infer_platform({"url": "https://example.com/x"}) is None


class TestParseCreatedAt:
    def test_iso_string_field(self):
        result = _parse_created_at({"createTimeISO": "2026-01-01T00:00:00Z"})
        assert result == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_twitter_legacy_created_at_format(self):
        # apidojo/tweet-scraper's actual createdAt format — confirmed against
        # a live dataset row; NOT ISO 8601, datetime.fromisoformat rejects it.
        result = _parse_created_at({"createdAt": "Mon Jul 20 11:56:36 +0000 2026"})
        assert result == datetime(2026, 7, 20, 11, 56, 36, tzinfo=timezone.utc)

    def test_epoch_field(self):
        result = _parse_created_at({"createTime": 1767225600})
        assert result is not None
        assert result.tzinfo is not None

    def test_missing_returns_none(self):
        assert _parse_created_at({}) is None


class TestFirstInt:
    def test_returns_first_present_numeric_key(self):
        assert _first_int({"viewCount": 42}, "playCount", "viewCount") == 42

    def test_skips_missing_keys(self):
        assert _first_int({"b": 7}, "a", "b", "c") == 7

    def test_no_match_defaults_to_zero(self):
        assert _first_int({}, "a", "b") == 0


class TestMapApifyItem:
    def test_full_tiktok_style_item_maps_cleanly(self, monkeypatch):
        monkeypatch.delenv("APIFY_PLATFORM", raising=False)
        item = {
            "id": "7123456789",
            "webVideoUrl": "https://www.tiktok.com/@user/video/7123456789",
            "text": "a trending video",
            "playCount": 120_000,
            "diggCount": 8_400,
            "shareCount": 310,
            "commentCount": 96,
            "createTimeISO": "2026-01-01T12:00:00Z",
        }
        mapped = map_apify_item(item)
        assert mapped == {
            "video_id": "7123456789",
            "platform": "tiktok",
            "description": "a trending video",
            "view_count": 120_000,
            "like_count": 8_400,
            "share_count": 310,
            "comment_count": 96,
            "created_at": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        }

    def test_missing_id_returns_none(self):
        assert map_apify_item({"createTimeISO": "2026-01-01T00:00:00Z"}) is None

    def test_unmappable_platform_returns_none(self, monkeypatch):
        monkeypatch.delenv("APIFY_PLATFORM", raising=False)
        item = {"id": "1", "url": "https://example.com", "createTimeISO": "2026-01-01T00:00:00Z"}
        assert map_apify_item(item) is None

    def test_missing_timestamp_returns_none(self, monkeypatch):
        monkeypatch.setenv("APIFY_PLATFORM", "tiktok")
        assert map_apify_item({"id": "1"}) is None


class TestResolveDatasetId:
    def test_dataset_id_env_var_is_used_directly_without_triggering_a_run(self, monkeypatch, mocker):
        monkeypatch.setenv("APIFY_DATASET_ID", "abc123")
        monkeypatch.delenv("APIFY_ACTOR_ID", raising=False)
        mock_client = mocker.Mock()
        assert _resolve_dataset_id(mock_client) == "abc123"
        mock_client.actor.assert_not_called()

    def test_actor_and_search_terms_trigger_a_fresh_run(self, monkeypatch, mocker):
        monkeypatch.delenv("APIFY_DATASET_ID", raising=False)
        monkeypatch.setenv("APIFY_ACTOR_ID", "apidojo/tweet-scraper")
        monkeypatch.setenv("APIFY_SEARCH_TERMS", "ai,startups")
        mock_client = mocker.Mock()
        mock_client.actor.return_value.call.return_value.default_dataset_id = "fresh-dataset-id"

        result = _resolve_dataset_id(mock_client)

        assert result == "fresh-dataset-id"
        mock_client.actor.assert_called_once_with("apidojo/tweet-scraper")
        call_kwargs = mock_client.actor.return_value.call.call_args.kwargs
        assert call_kwargs["run_input"]["searchTerms"] == ["ai", "startups"]

    def test_neither_configured_raises_clear_error(self, monkeypatch, mocker):
        monkeypatch.delenv("APIFY_DATASET_ID", raising=False)
        monkeypatch.delenv("APIFY_ACTOR_ID", raising=False)
        monkeypatch.delenv("APIFY_SEARCH_TERMS", raising=False)
        with pytest.raises(RuntimeError, match="APIFY_DATASET_ID"):
            _resolve_dataset_id(mocker.Mock())

    def test_dataset_id_takes_priority_over_actor_run(self, monkeypatch, mocker):
        # Cheapest path wins when both are configured — no reason to trigger
        # a paid run when a specific dataset was explicitly requested.
        monkeypatch.setenv("APIFY_DATASET_ID", "abc123")
        monkeypatch.setenv("APIFY_ACTOR_ID", "apidojo/tweet-scraper")
        monkeypatch.setenv("APIFY_SEARCH_TERMS", "ai")
        mock_client = mocker.Mock()
        assert _resolve_dataset_id(mock_client) == "abc123"
        mock_client.actor.assert_not_called()


class TestTriggerActorRun:
    def test_empty_run_result_raises(self, mocker):
        mock_client = mocker.Mock()
        mock_client.actor.return_value.call.return_value = None
        with pytest.raises(RuntimeError, match="no result"):
            _trigger_actor_run(mock_client, "some/actor", ["term"], 60)
