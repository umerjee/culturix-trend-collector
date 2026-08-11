"""Google Trends "Daily Search Trends" collector — the RSS feed at
trends.google.com/trending/rss?geo={region}, not any official public API
(Google doesn't publish one for this). Free, no auth, no third-party proxy
in the chain — confirmed live: a plain httpx GET with just a User-Agent
header returns a well-formed RSS 2.0 feed with a custom "ht" namespace
(approx_traffic, picture, and one or more news_item children per trend),
genuinely region-specific across real geo values (confirmed US vs GB
returning different results). Same "unofficial but no proxy dependency"
shape as wikipedia.py's pageviews API — meaningfully more robust than
twitter.py's Jina-proxy-wrapped scrape, but still monitored via
app/integration_health.py since Google could change or remove this feed
without notice at any time, same reasoning as this app's other unofficial
integrations there.
"""
import logging
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx

logger = logging.getLogger("culturix.collectors.google_trends")

_BASE = "https://trends.google.com/trending/rss"
_HEADERS = {"User-Agent": "culturix-trend-collector/1.0 (contact: umer.ali79@gmail.com)"}
_NS = {"ht": "https://trends.google.com/trending/rss"}

# A representative geo spread rather than every country Google Trends
# supports — mirrors wikipedia.py's PROJECTS list's own reasoning
# (geographic/cultural spread, not exhaustiveness). All real ISO-2 codes
# that app.collectors.region_codes.normalize_region() passes through
# unchanged. CN is included despite this app's own documented "CN is
# permanently broken" gap (see app/regions.py's docstring) — that gap is
# specifically about Xiaohongshu contributing zero CN-tagged rows, not a
# Google Trends limitation; this may be the first collector to actually
# produce real CN-region rows.
DEFAULT_REGIONS = ["US", "GB", "FR", "DE", "IT", "PT", "CA", "AU", "CN"]

# The RSS item's own <title> is a bare search query, in whatever language
# is dominant for that region — unlike wikipedia.py's article titles, these
# aren't reliably English even for "content", so this maps region -> the
# query's likely language for Trend.language (the wrapper `content` sentence
# built below is always English regardless, same as translated_content).
_REGION_TO_LANGUAGE = {
    "US": "en", "GB": "en", "CA": "en", "AU": "en",
    "FR": "fr", "DE": "de", "IT": "it", "PT": "pt", "CN": "zh",
}


def fetch_trending(region: str = "US", limit: int = 20) -> list:
    """Returns up to `limit` trend dicts: {title, traffic, pub_date, image_url,
    news_items: [{title, url, source}]}. [] on any failure — a feed outage
    or shape change must not block the other regions/collectors in the
    same run."""
    try:
        resp = httpx.get(_BASE, params={"geo": region}, headers=_HEADERS, timeout=15.0)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except Exception as e:
        logger.warning("Google Trends fetch failed for region=%s: %s", region, e)
        return []

    items = []
    for item in root.findall(".//item")[:limit]:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        news_items = []
        for news in item.findall("ht:news_item", _NS):
            news_title = (news.findtext("ht:news_item_title", "", _NS) or "").strip()
            if not news_title:
                continue
            news_items.append({
                "title": news_title,
                "url": (news.findtext("ht:news_item_url", "", _NS) or "").strip(),
                "source": (news.findtext("ht:news_item_source", "", _NS) or "").strip(),
            })
        items.append({
            "title": title,
            "traffic": (item.findtext("ht:approx_traffic", "", _NS) or "").strip(),
            "pub_date": (item.findtext("pubDate") or "").strip(),
            "image_url": (item.findtext("ht:picture", "", _NS) or "").strip() or None,
            "news_items": news_items,
        })
    return items


def _approx_traffic_to_int(traffic: str) -> int:
    """"1000+" -> 1000, "" or unparsable -> 0 — Google's own format for this
    field in the live feed, a rough order-of-magnitude search-interest
    signal rather than a precise count."""
    digits = "".join(ch for ch in traffic if ch.isdigit())
    return int(digits) if digits else 0


def store_google_trends_trends(regions: list = None, limit: int = 20) -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.collectors.region_codes import normalize_region

    session = SessionLocal()
    inserted = 0
    day = datetime.now(timezone.utc).date().isoformat()

    try:
        for region in (regions or DEFAULT_REGIONS):
            for t in fetch_trending(region, limit=limit):
                external_id = f"{region}:{day}:{t['title']}"
                exists = session.query(Trend).filter_by(
                    platform="google_trends", external_id=external_id
                ).first()
                if exists:
                    continue

                traffic_score = _approx_traffic_to_int(t["traffic"])
                news_summary = "; ".join(n["title"] for n in t["news_items"][:3])
                traffic_note = f" ({t['traffic']} searches)" if t["traffic"] else ""
                news_note = f" Related: {news_summary}" if news_summary else ""
                content = f"\"{t['title']}\" is trending on Google Search{traffic_note}.{news_note}"

                trend = Trend(
                    platform="google_trends",
                    external_id=external_id,
                    url=f"https://trends.google.com/trends/explore?q={t['title'].replace(' ', '+')}&geo={region}",
                    title=t["title"],
                    content=content,
                    translated_content=content,  # wrapper text is already English regardless of query language
                    language=_REGION_TO_LANGUAGE.get(region, "en"),
                    likes=traffic_score,
                    image_url=t["image_url"],
                    raw_json=t,
                    region=normalize_region(region),
                )
                session.add(trend)
                try:
                    # Per-row commit — same SQLAlchemy batched-insert/JSON
                    # issue found and fixed in the TikTok/Reddit/Wikipedia
                    # collectors.
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
