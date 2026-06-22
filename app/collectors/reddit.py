import httpx
from datetime import datetime

from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language, translate_to_english_if_needed

REDDIT_BASE = "https://www.reddit.com"
HEADERS = {"User-Agent": "culturix-trend-collector/0.1"}

# Subreddits that surface culture, trends, and viral content
SUBREDDITS = [
    ("all",         "top",  "day"),
    ("popular",     "top",  "day"),
    ("all",         "hot",  None),
    ("worldnews",   "top",  "day"),
    ("entertainment","top", "day"),
    ("Music",       "top",  "day"),
    ("movies",      "hot",  None),
    ("Futurology",  "hot",  None),
    ("TikTokCringe","top",  "week"),
    ("streetwear",  "top",  "week"),
    ("malefashionadvice", "top", "week"),
    ("beauty",      "top",  "week"),
    ("LifeProTips", "hot",  None),
    ("technology",  "top",  "day"),
]


def fetch_subreddit(subreddit: str, sort: str = "top", time_filter: str | None = "day", limit: int = 100) -> list:
    params = f"?limit={limit}" + (f"&t={time_filter}" if time_filter else "")
    url = f"{REDDIT_BASE}/r/{subreddit}/{sort}.json{params}"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=15.0)
        resp.raise_for_status()
        return resp.json()["data"]["children"]
    except Exception:
        return []


def store_reddit_trends(limit=100):
    session = SessionLocal()
    inserted = 0

    try:
        seen_in_run: set[str] = set()
        for subreddit, sort, time_filter in SUBREDDITS:
            posts = fetch_subreddit(subreddit, sort, time_filter, limit)
            for p in posts:
                d = p["data"]
                post_id = d.get("id")
                if not post_id or post_id in seen_in_run:
                    continue
                seen_in_run.add(post_id)

                exists = session.query(Trend).filter_by(external_id=post_id).first()
                if exists:
                    continue

                content = f"{d.get('title') or ''}\n{d.get('selftext') or ''}".strip()
                lang = detect_language(content)
                translated = translate_to_english_if_needed(content, lang)

                trend = Trend(
                    platform="reddit",
                    external_id=post_id,
                    url=f"{REDDIT_BASE}{d['permalink']}",
                    title=d.get("title"),
                    content=content,
                    translated_content=translated,
                    language=lang,
                    author=d.get("author"),
                    likes=d.get("ups"),
                    comments=d.get("num_comments"),
                    posted_at=datetime.fromtimestamp(d["created_utc"]),
                    raw_json=d,
                )
                session.add(trend)
                inserted += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return inserted
