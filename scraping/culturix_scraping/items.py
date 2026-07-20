"""
Item contract for the velocity pipeline.

TrendItem is the loose Scrapy Item a spider yields — spiders are intentionally
out of scope here, but this is the shape process_item() expects: video_id,
platform, description, view_count, like_count, share_count, comment_count,
created_at.

TrendRecord is the strictly-typed, validated form the pipeline actually
operates on. Coercion/validation happens once, at the boundary
(TrendRecord.from_item), so every downstream function (velocity.py, db.py,
hooks.py) can assume clean types instead of re-checking a raw dict.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import scrapy


class TrendItem(scrapy.Item):
    video_id = scrapy.Field()
    platform = scrapy.Field()
    description = scrapy.Field()
    view_count = scrapy.Field()
    like_count = scrapy.Field()
    share_count = scrapy.Field()
    comment_count = scrapy.Field()
    created_at = scrapy.Field()


@dataclass(frozen=True)
class TrendRecord:
    video_id: str
    platform: str
    description: str
    view_count: int
    like_count: int
    share_count: int
    comment_count: int
    created_at: datetime

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "TrendRecord":
        video_id = str(item.get("video_id") or "").strip()
        platform = str(item.get("platform") or "").strip().lower()
        if not video_id or not platform:
            raise ValueError(f"video_id and platform are required, got: {item!r}")

        created_at = item.get("created_at")
        if isinstance(created_at, (int, float)):
            created_at = datetime.fromtimestamp(created_at, tz=timezone.utc)
        elif isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        elif not isinstance(created_at, datetime):
            raise ValueError(f"created_at must be a datetime, epoch number, or ISO string, got: {created_at!r}")

        return cls(
            video_id=video_id,
            platform=platform,
            description=str(item.get("description") or ""),
            view_count=int(item.get("view_count") or 0),
            like_count=int(item.get("like_count") or 0),
            share_count=int(item.get("share_count") or 0),
            comment_count=int(item.get("comment_count") or 0),
            created_at=created_at,
        )
