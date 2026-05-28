import httpx
from datetime import datetime

from app.db import SessionLocal
from app.models.trend import Trend

REDDIT_BASE = "https://www.reddit.com"
HEADERS = {"User-Agent": "culturix-trend-collector/0.1"}


def fetch_reddit_trending(limit=50):
    url = f"{REDDIT_BASE}/r/all/top.json?t=day&limit={limit}"
    resp = httpx.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["data"]["children"]


def store_reddit_trends(limit=50):
    session = SessionLocal()
    posts = fetch_reddit_trending(limit)

    inserted = 0

    for p in posts:
        d = p["data"]

        # Skip if already stored
        exists = session.query(Trend).filter_by(external_id=d["id"]).first()
        if exists:
            continue

        trend = Trend(
            platform="reddit",
            external_id=d["id"],
            url=f"{REDDIT_BASE}{d['permalink']}",
            title=d.get("title"),
            content=d.get("selftext") or "",
            author=d.get("author"),
            likes=d.get("ups"),
            comments=d.get("num_comments"),
            posted_at=datetime.fromtimestamp(d["created_utc"]),
            raw_json=d,
        )

        session.add(trend)
        inserted += 1

    session.commit()
    session.close()

    return inserted
