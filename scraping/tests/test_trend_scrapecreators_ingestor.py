from datetime import datetime, timezone

from culturix_scraping.collectors.trend_scrapecreators_ingestor import (
    _extract_items,
    _first_int,
    _parse_created_at,
    map_scrapecreators_item,
)


class TestExtractItems:
    def test_tiktok_uses_known_aweme_list_key(self):
        payload = {"aweme_list": [{"id": "1"}, {"id": "2"}], "other_stuff": {}}
        assert _extract_items("tiktok", payload) == [{"id": "1"}, {"id": "2"}]

    def test_bare_list_response_is_used_directly(self):
        payload = [{"id": "1"}]
        assert _extract_items("instagram", payload) == [{"id": "1"}]

    def test_falls_back_to_common_candidate_keys(self):
        payload = {"posts": [{"id": "1"}]}
        assert _extract_items("instagram", payload) == [{"id": "1"}]

    def test_no_matching_key_returns_empty_list(self):
        payload = {"something_unexpected": []}
        assert _extract_items("instagram", payload) == []


class TestFirstInt:
    def test_reads_one_level_of_nesting(self):
        item = {"statistics": {"digg_count": 42}}
        assert _first_int(item, "statistics.digg_count") == 42

    def test_falls_back_through_multiple_paths(self):
        item = {"video_play_count": 99}
        assert _first_int(item, "statistics.play_count", "video_view_count", "video_play_count") == 99

    def test_missing_nested_parent_does_not_raise(self):
        item = {"statistics": None}
        assert _first_int(item, "statistics.digg_count") == 0

    def test_no_match_defaults_to_zero(self):
        assert _first_int({}, "a.b", "c") == 0


class TestParseCreatedAt:
    def test_tiktok_epoch_seconds(self):
        result = _parse_created_at({"create_time": 1767225600})
        assert result == datetime.fromtimestamp(1767225600, tz=timezone.utc)

    def test_instagram_iso_with_milliseconds(self):
        result = _parse_created_at({"taken_at": "2025-09-05T12:51:42.000Z"})
        assert result == datetime(2025, 9, 5, 12, 51, 42, tzinfo=timezone.utc)

    def test_missing_returns_none(self):
        assert _parse_created_at({}) is None


class TestMapScrapeCreatorsItem:
    def test_tiktok_item_with_nested_statistics_maps_cleanly(self):
        item = {
            "aweme_id": "7123456789",
            "desc": "a trending video",
            "create_time": 1767225600,
            "statistics": {
                "play_count": 120_000,
                "digg_count": 8_400,
                "share_count": 310,
                "comment_count": 96,
            },
        }
        mapped = map_scrapecreators_item("tiktok", item)
        assert mapped == {
            "video_id": "7123456789",
            "platform": "tiktok",
            "description": "a trending video",
            "view_count": 120_000,
            "like_count": 8_400,
            "share_count": 310,
            "comment_count": 96,
            "created_at": datetime.fromtimestamp(1767225600, tz=timezone.utc),
        }

    def test_instagram_item_with_flat_fields_and_no_share_count(self):
        item = {
            "id": "3714950709444987377",
            "caption": "a reel",
            "taken_at": "2025-09-05T12:51:42.000Z",
            "like_count": 35854,
            "comment_count": 1263,
            "video_view_count": 148581,
        }
        mapped = map_scrapecreators_item("instagram", item)
        assert mapped["video_id"] == "3714950709444987377"
        assert mapped["like_count"] == 35854
        assert mapped["view_count"] == 148581
        assert mapped["share_count"] == 0  # Instagram has no share_count field

    def test_missing_id_returns_none(self):
        assert map_scrapecreators_item("tiktok", {"create_time": 1767225600}) is None

    def test_missing_timestamp_returns_none(self):
        assert map_scrapecreators_item("tiktok", {"aweme_id": "1"}) is None
