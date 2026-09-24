"""Wikipedia article EXTRACT fetcher — real encyclopedic text for a given
topic, via the official REST summary API. Distinct from wikipedia.py (that
one pulls trending page-VIEW counts across language editions, never the
article body itself — see its own module docstring). This one is the raw
text source for app/services/culturix_ingestion.py — a specific topic the
curator already has in mind, not an autonomous discovery mechanism, so
unlike every other collector in this package it is NOT wired into
app/collectors/orchestrator.py's scheduled sweep.

Free, no API key, no auth — confirmed live against
en.wikipedia.org/api/rest_v1/page/summary/Strait_of_Hormuz before this was
written.
"""
import logging
import re

import httpx

logger = logging.getLogger("culturix.collectors.wikipedia_extracts")

_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary"
_HEADERS = {"User-Agent": "culturix-trend-collector/1.0 (contact: umer.ali79@gmail.com)"}


_API = "https://en.wikipedia.org/w/api.php"


def _fetch_article_text(title: str, max_chars: int) -> str | None:
    """Plain-text body of a real article (lead + sections) via the MediaWiki
    extracts API, truncated to max_chars. None on any failure."""
    try:
        resp = httpx.get(
            _API,
            params={"action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "plain",
                    "redirects": 1, "titles": title, "format": "json", "formatversion": 2},
            headers=_HEADERS, timeout=15.0,
        )
        if not resp.is_success:
            return None
        pages = resp.json().get("query", {}).get("pages") or []
        text = (pages[0].get("extract") or "").strip() if pages else ""
    except Exception as e:
        logger.warning("Wikipedia full-text fetch failed for %r: %s", title, e)
        return None
    return text[:max_chars] if text else None


def fetch_wikipedia_extract(title: str, full_text: bool = False, max_chars: int = 6000) -> dict | None:
    """Returns {title, extract, url, thumbnail_url, coordinates: {lat, lon} | None} for a
    real Wikipedia article, or None on any failure (unknown title, disambig
    page with no extract, network error) — never raises, matching every
    other collector's fetch_* convention in this package.

    thumbnail_url is the article's own lead image — the REST summary API returns it for
    free in the same response as the extract, so capturing it costs nothing extra and
    gives every World subject a real, topic-representative photo instead of relying on a
    frame grabbed from the eventually-generated video. None when the article has no lead
    image (common for abstract/phenomenon topics)."""
    try:
        resp = httpx.get(f"{_BASE}/{title.replace(' ', '_')}", headers=_HEADERS, timeout=15.0)
        if not resp.is_success:
            logger.warning("Wikipedia extract fetch failed for %r: HTTP %s", title, resp.status_code)
            return None
        data = resp.json()
    except Exception as e:
        logger.warning("Wikipedia extract fetch failed for %r: %s", title, e)
        return None

    extract = (data.get("extract") or "").strip()
    if not extract:
        return None

    if full_text:
        # A 30-60s video needs more than the lead paragraph; fall back to the
        # summary extract if the full body can't be fetched.
        extract = _fetch_article_text(data.get("title") or title, max_chars) or extract

    coords = data.get("coordinates") or []
    if isinstance(coords, list):
        coords = coords[0] if coords else {}
    return {
        "title": data.get("title") or title,
        "extract": extract,
        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
        "thumbnail_url": (data.get("thumbnail") or {}).get("source"),
        "coordinates": {"lat": coords["lat"], "lon": coords["lon"]} if "lat" in coords and "lon" in coords else None,
    }


_STOPWORDS = {"the", "of", "and", "de", "la", "le", "les", "du", "des", "in", "its", "at", "on", "a", "an",
              "historic", "historical", "old", "city", "site", "sites", "town", "centre", "center"}


def _significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]{3,}", text.lower()) if w not in _STOPWORDS}


def find_wikipedia_article(name: str, max_chars: int = 3500) -> dict | None:
    """Best-matching real Wikipedia article for a free-text name (e.g. a UNESCO
    site name), or None. A search hit is only accepted when its title shares a
    significant word with the name — a wrong-article match would feed the video
    script confident facts about the wrong subject, which the fact-checker
    would then wave through as 'supported'."""
    try:
        resp = httpx.get(
            _API,
            params={"action": "opensearch", "search": name, "limit": 3, "namespace": 0, "format": "json"},
            headers=_HEADERS, timeout=15.0,
        )
        if not resp.is_success:
            return None
        titles = resp.json()[1]
    except Exception as e:
        logger.warning("Wikipedia search failed for %r: %s", name, e)
        return None
    wanted = _significant_words(name)
    for title in titles:
        if wanted & _significant_words(title):
            return fetch_wikipedia_extract(title, full_text=True, max_chars=max_chars)
    return None
