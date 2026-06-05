import os
import httpx
from dotenv import load_dotenv
from urllib.parse import unquote_plus
from datetime import datetime

from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language, translate_to_english_if_needed


# Ensure environment variables from .env are loaded when this module is used directly
load_dotenv()

# Try normal env first, but fall back to reading .env if dotenv misses the key
_raw_bearer = os.getenv("TWITTER_BEARER_TOKEN")
if not _raw_bearer:
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('TWITTER_BEARER_TOKEN='):
                    _raw_bearer = line.strip().split('=', 1)[1]
                    break
    except Exception:
        _raw_bearer = None

TWITTER_BEARER = unquote_plus(_raw_bearer) if _raw_bearer else None
TWITTER_TRENDS_URL = "https://api.twitter.com/1.1/trends/place.json"


WOEIDS = {
    "global": 1,
    "us": 23424977,
    "uk": 23424975,
    "india": 23424848,
    "japan": 23424856,
    "uae": 23424738,
}


def _get_bearer_from_env():
    # Resolve token at call time so running processes pick up environment changes
    raw = os.getenv("TWITTER_BEARER_TOKEN")
    if not raw:
        try:
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('TWITTER_BEARER_TOKEN='):
                        raw = line.strip().split('=', 1)[1]
                        break
        except Exception:
            raw = None
    return unquote_plus(raw) if raw else None


def _build_headers():
    bearer = _get_bearer_from_env()
    if not bearer:
        return None
    return {"Authorization": f"Bearer {bearer}", "User-Agent": "culturix-trend-collector/0.1"}


def fetch_twitter_trending(region="global"):
    headers = _build_headers()
    if headers is None:
        raise RuntimeError("TWITTER_BEARER_TOKEN not set in environment")

    woeid = WOEIDS.get(region.lower(), 1)
    resp = httpx.get(TWITTER_TRENDS_URL, params={"id": woeid}, headers=headers, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()
    # Twitter returns a list; first item contains 'trends'
    if isinstance(data, list) and data:
        return data[0].get("trends", [])
    return []


def store_twitter_trends(region="global"):
    headers = _build_headers()
    if headers is None:
        # Graceful fallback: nothing to do without credentials
        return 0

    session = SessionLocal()
    try:
        items = fetch_twitter_trending(region)
    except Exception:
        session.close()
        raise

    inserted = 0
    for item in items:
        name = item.get("name") or ""
        url = item.get("url")

        # Skip duplicates by external_id
        exists = session.query(Trend).filter_by(platform="twitter", external_id=name).first()
        if exists:
            continue

        lang = detect_language(name)
        translated = translate_to_english_if_needed(name, lang)

        trend = Trend(
            platform="twitter",
            external_id=name,
            url=url,
            title=name,
            content=name,
            translated_content=translated,
            language=lang,
            author=None,
            likes=None,
            comments=None,
            posted_at=datetime.utcnow(),
            raw_json=item,
        )

        session.add(trend)
        inserted += 1

    session.commit()
    session.close()
    return inserted
