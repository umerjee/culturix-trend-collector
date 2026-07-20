import json
from datetime import datetime, timezone

from culturix_scraping.items import TrendRecord
from culturix_scraping.pipelines import build_upsert_values


class TestBuildUpsertValues:
    def test_raw_json_is_actually_json_serializable(self):
        # Regression: raw_json used to be built from the caller's raw item
        # dict, which can carry created_at as a datetime (TrendRecord.from_item
        # accepts one) — datetime isn't JSON-serializable, so the upsert failed
        # for every single row the first time this ran against real Apify data.
        record = TrendRecord.from_item({
            "video_id": "123", "platform": "twitter", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        })
        values = build_upsert_values(record, score=42.0)
        json.dumps(values["raw_json"])  # must not raise

    def test_maps_record_fields_onto_trends_columns(self):
        record = TrendRecord.from_item({
            "video_id": "123", "platform": "TikTok", "description": "hello",
            "view_count": 10, "like_count": 5, "share_count": 2, "comment_count": 1,
            "created_at": "2026-01-01T00:00:00Z",
        })
        values = build_upsert_values(record, score=5.0)
        assert values["external_id"] == "123"
        assert values["platform"] == "tiktok"
        assert values["content"] == "hello"
        assert values["likes"] == 5
        assert values["comments"] == 1
        assert values["shares"] == 2
        assert values["views"] == 10
        assert values["velocity_score"] == 5.0
        assert values["posted_at"] == datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)

    def test_title_truncates_long_description(self):
        record = TrendRecord.from_item({
            "video_id": "1", "platform": "twitter", "description": "x" * 500,
            "created_at": "2026-01-01T00:00:00Z",
        })
        values = build_upsert_values(record, score=0.0)
        assert len(values["title"]) == 200

    def test_posted_at_is_tz_naive_for_aware_input(self):
        # Regression: trends.posted_at is TIMESTAMP WITHOUT TIME ZONE — asyncpg
        # rejects a tz-aware datetime against it outright. Every real Apify
        # timestamp (Twitter's createdAt included) parses as tz-aware.
        record = TrendRecord.from_item({
            "video_id": "1", "platform": "twitter", "created_at": "2026-01-01T12:00:00Z",
        })
        values = build_upsert_values(record, score=0.0)
        assert values["posted_at"].tzinfo is None
        assert values["posted_at"] == datetime(2026, 1, 1, 12, 0, 0)

    def test_posted_at_passes_through_naive_input_unchanged(self):
        record = TrendRecord.from_item({
            "video_id": "1", "platform": "twitter",
            "created_at": datetime(2026, 1, 1, 12, 0, 0),  # no tzinfo
        })
        values = build_upsert_values(record, score=0.0)
        assert values["posted_at"] == datetime(2026, 1, 1, 12, 0, 0)
