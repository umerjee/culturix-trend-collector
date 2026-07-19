"""
Reddit collector via PRAW (OAuth read-only app).

Previously used unauthenticated requests straight to reddit.com/*.json —
Reddit is well known to block/rate-limit that from datacenter IPs (Railway
included), which is almost certainly why this has collected zero rows.
PRAW + a registered "script" app avoids that entirely.

Requires REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET env vars. Create a read-only
app at https://www.reddit.com/prefs/apps -> "create app" -> type "script"
(any name/redirect URI works, they're not used in read-only mode) -> the
string under the app name is the client ID, "secret" is the client secret.
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("culturix.collectors.reddit")

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


def _get_reddit_client():
    import os
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    import praw
    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="culturix-trend-collector/0.2 (read-only trend collector)",
    )


def fetch_subreddit(reddit, subreddit: str, sort: str = "top", time_filter: Optional[str] = "day", limit: int = 100) -> list:
    try:
        sub = reddit.subreddit(subreddit)
        listing = sub.top(time_filter=time_filter or "day", limit=limit) if sort == "top" else sub.hot(limit=limit)
        return list(listing)
    except Exception as e:
        logger.warning("Reddit fetch failed for r/%s: %s", subreddit, e)
        return []


def store_reddit_trends(limit=100):
    reddit = _get_reddit_client()
    if not reddit:
        logger.warning("REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not set — skipping Reddit collection")
        return 0

    session = None
    try:
        from app.db import SessionLocal
        from app.models.trend import Trend
        from app.language import detect_language

        session = SessionLocal()
        inserted = 0
        seen_in_run: set[str] = set()

        for subreddit, sort, time_filter in SUBREDDITS:
            posts = fetch_subreddit(reddit, subreddit, sort, time_filter, limit)
            for post in posts:
                post_id = post.id
                if not post_id or post_id in seen_in_run:
                    continue
                seen_in_run.add(post_id)

                exists = session.query(Trend).filter_by(platform="reddit", external_id=post_id).first()
                if exists:
                    continue

                content = f"{post.title or ''}\n{post.selftext or ''}".strip()
                lang = detect_language(content)

                trend = Trend(
                    platform="reddit",
                    external_id=post_id,
                    url=f"https://www.reddit.com{post.permalink}",
                    title=post.title,
                    content=content,
                    translated_content=None,
                    language=lang,
                    author=str(post.author) if post.author else None,
                    likes=post.score,
                    comments=post.num_comments,
                    posted_at=datetime.utcfromtimestamp(post.created_utc),
                    raw_json={
                        "id": post.id,
                        "subreddit": subreddit,
                        "title": post.title,
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "permalink": post.permalink,
                        "over_18": bool(getattr(post, "over_18", False)),
                    },
                )
                session.add(trend)
                try:
                    # Commit per row — SQLAlchemy 2.0's batched multi-row
                    # insert can fail to adapt dict raw_json when many rows
                    # flush together in one statement (same issue found and
                    # fixed in the TikTok collector); this also isolates a
                    # single bad row from the rest of the run.
                    session.commit()
                    inserted += 1
                except Exception:
                    session.rollback()

        return inserted
    except Exception:
        if session:
            session.rollback()
        raise
    finally:
        if session:
            session.close()
