from datetime import datetime, timezone

import pytest

from culturix_scraping.items import TrendRecord


class TestTrendRecordFromItem:
    def test_valid_item_parses_cleanly(self):
        record = TrendRecord.from_item({
            "video_id": "abc123",
            "platform": "TikTok",
            "description": "a trending video",
            "view_count": 10_000,
            "like_count": 500,
            "share_count": 20,
            "comment_count": 15,
            "created_at": "2026-01-01T00:00:00Z",
        })
        assert record.video_id == "abc123"
        assert record.platform == "tiktok"  # normalized lowercase
        assert record.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_missing_video_id_raises(self):
        with pytest.raises(ValueError):
            TrendRecord.from_item({"platform": "tiktok", "created_at": "2026-01-01T00:00:00Z"})

    def test_missing_platform_raises(self):
        with pytest.raises(ValueError):
            TrendRecord.from_item({"video_id": "abc123", "created_at": "2026-01-01T00:00:00Z"})

    def test_epoch_timestamp_is_accepted(self):
        record = TrendRecord.from_item({
            "video_id": "abc123", "platform": "tiktok", "created_at": 1767225600,
        })
        assert record.created_at.tzinfo is not None

    def test_missing_counts_default_to_zero(self):
        record = TrendRecord.from_item({
            "video_id": "abc123", "platform": "tiktok", "created_at": "2026-01-01T00:00:00Z",
        })
        assert record.view_count == 0
        assert record.like_count == 0

    def test_invalid_created_at_type_raises(self):
        with pytest.raises(ValueError):
            TrendRecord.from_item({"video_id": "abc123", "platform": "tiktok", "created_at": object()})
