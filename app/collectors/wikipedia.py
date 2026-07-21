"""
Wikipedia Trending Topics collector — official Wikimedia Pageviews REST API.
Free, no API key, no auth — just a User-Agent header. Added as a Reddit
replacement after Reddit's 2026 "Responsible Builder Policy" made API access
require a multi-week approval process instead of self-serve app creation.

Pulls "most viewed articles" per Wikipedia language edition for the previous
day (today's numbers aren't finalized yet), across a handful of major
languages for geographic/cultural spread rather than English-only.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger("culturix.collectors.wikipedia")

_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top"
_HEADERS = {"User-Agent": "culturix-trend-collector/1.0 (contact: umer.ali79@gmail.com)"}

# Wikipedia language editions to pull from — gives geographic/cultural spread
PROJECTS = ["en.wikipedia", "es.wikipedia", "fr.wikipedia", "de.wikipedia", "ja.wikipedia"]

# Meta/navigation pages that show up in every day's top list but aren't real trends
_NOISE_PREFIXES = ("Special:", "Wikipedia:", "Main_Page", "Portal:", "Wikipédia:", "Wikipedia_talk:")

# de/fr/ja map cleanly to a single country (Germany/France/Japan). es/en don't
# get a region — Spanish and English are each spoken across too many
# countries (Spain vs. Latin America; US/UK/Australia/Canada/global) to
# confidently assign one, and an incorrect guess is worse than "unknown"
# here since persona_mapper.py's filter fails open on unknown regions but
# would wrongly exclude a real one.
_LANG_TO_REGION = {"de": "DE", "fr": "FR", "ja": "JP"}


def fetch_top_articles(project: str = "en.wikipedia", date: Optional[datetime] = None, limit: int = 30) -> list:
    d = date or (datetime.utcnow() - timedelta(days=1))
    url = f"{_BASE}/{project}/all-access/{d.year}/{d.month:02d}/{d.day:02d}"
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=15.0)
        resp.raise_for_status()
        items = resp.json().get("items") or [{}]
        articles = items[0].get("articles") or []
    except Exception as e:
        logger.warning("Wikipedia pageviews fetch failed for %s: %s", project, e)
        return []

    filtered = [a for a in articles if not a.get("article", "").startswith(_NOISE_PREFIXES)]
    return filtered[:limit]


def store_wikipedia_trends(limit: int = 30) -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend

    session = SessionLocal()
    inserted = 0
    day = (datetime.utcnow() - timedelta(days=1)).date().isoformat()

    try:
        for project in PROJECTS:
            lang = project.split(".")[0]
            wiki_domain = project.replace(".wikipedia", "") + ".wikipedia.org"

            for a in fetch_top_articles(project, limit=limit):
                article = a.get("article", "")
                if not article:
                    continue

                external_id = f"{project}:{day}:{article}"
                exists = session.query(Trend).filter_by(
                    platform="wikipedia", external_id=external_id
                ).first()
                if exists:
                    continue

                title = article.replace("_", " ")
                views = a.get("views", 0)
                content = (
                    f"{title} is trending on Wikipedia ({lang}) with {views:,} views "
                    f"yesterday (rank #{a.get('rank')})"
                )

                trend = Trend(
                    platform="wikipedia",
                    external_id=external_id,
                    url=f"https://{wiki_domain}/wiki/{article}",
                    title=title,
                    content=content,
                    translated_content=content,  # wrapper text is already English regardless of source wiki
                    language=lang,
                    likes=views,
                    raw_json=a,
                    region=_LANG_TO_REGION.get(lang),
                )
                session.add(trend)
                try:
                    # Per-row commit — same SQLAlchemy batched-insert/JSON
                    # issue found and fixed in the TikTok/Reddit collectors.
                    session.commit()
                    inserted += 1
                except Exception:
                    session.rollback()

        return inserted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
