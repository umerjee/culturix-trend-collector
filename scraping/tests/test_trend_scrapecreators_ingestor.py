from datetime import datetime, timezone

from culturix_scraping.collectors.trend_scrapecreators_ingestor import (
    _SEARCH_PARAM_NAME,
    _extract_items,
    _first_int,
    _first_str,
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

    def test_threads_uses_known_posts_key(self):
        payload = {"posts": [{"id": "1"}, {"id": "2"}]}
        assert _extract_items("threads", payload) == [{"id": "1"}, {"id": "2"}]

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


class TestFirstStr:
    def test_reads_nested_path(self):
        assert _first_str({"caption": {"text": "hello"}}, "caption.text") == "hello"

    def test_skips_a_path_whose_value_is_not_a_string(self):
        # Instagram's `caption` is a flat string; Threads' `caption` is a dict
        # with the text nested under it — the dict must not stringify, it
        # should fall through to the next candidate path.
        item = {"caption": {"text": "nested text"}}
        assert _first_str(item, "caption", "caption.text") == "nested text"

    def test_no_match_defaults_to_empty_string(self):
        assert _first_str({}, "a", "b.c") == ""


class TestParseCreatedAt:
    def test_tiktok_epoch_seconds(self):
        result = _parse_created_at({"create_time": 1767225600})
        assert result == datetime.fromtimestamp(1767225600, tz=timezone.utc)

    def test_instagram_iso_with_milliseconds(self):
        result = _parse_created_at({"taken_at": "2025-09-05T12:51:42.000Z"})
        assert result == datetime(2025, 9, 5, 12, 51, 42, tzinfo=timezone.utc)

    def test_threads_taken_at_as_epoch_int(self):
        # Same field name as Instagram's taken_at, but an int here, not a
        # string — must not be confused with the ISO-string branch.
        result = _parse_created_at({"taken_at": 1746200860})
        assert result == datetime.fromtimestamp(1746200860, tz=timezone.utc)

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

    def test_threads_item_with_nested_caption_and_reply_info(self):
        item = {
            "id": "3141592653589793238_67890",
            "pk": "3141592653589793238",
            "taken_at": 1746200860,
            "caption": {"text": "hot take on basketball"},
            "like_count": 4093,
            "text_post_app_info": {
                "direct_reply_count": 212,
                "repost_count": 58,
                "quote_count": 9,
            },
        }
        mapped = map_scrapecreators_item("threads", item)
        assert mapped == {
            "video_id": "3141592653589793238_67890",
            "platform": "threads",
            "description": "hot take on basketball",
            "view_count": 0,  # threads has no view_count field
            "like_count": 4093,
            "share_count": 58,
            "comment_count": 212,
            "created_at": datetime.fromtimestamp(1746200860, tz=timezone.utc),
        }

    def test_missing_id_returns_none(self):
        assert map_scrapecreators_item("tiktok", {"create_time": 1767225600}) is None

    def test_missing_timestamp_returns_none(self):
        assert map_scrapecreators_item("tiktok", {"aweme_id": "1"}) is None


class TestSearchParamName:
    def test_tiktok_and_instagram_use_hashtag(self):
        assert _SEARCH_PARAM_NAME["tiktok"] == "hashtag"
        assert _SEARCH_PARAM_NAME["instagram"] == "hashtag"

    def test_threads_uses_query(self):
        assert _SEARCH_PARAM_NAME["threads"] == "query"
