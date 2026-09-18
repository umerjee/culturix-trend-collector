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

import httpx

logger = logging.getLogger("culturix.collectors.wikipedia_extracts")

_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary"
_HEADERS = {"User-Agent": "culturix-trend-collector/1.0 (contact: umer.ali79@gmail.com)"}


def fetch_wikipedia_extract(title: str) -> dict | None:
    """Returns {title, extract, url, coordinates: {lat, lon} | None} for a
    real Wikipedia article, or None on any failure (unknown title, disambig
    page with no extract, network error) — never raises, matching every
    other collector's fetch_* convention in this package."""
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

    coords = data.get("coordinates") or []
    if isinstance(coords, list):
        coords = coords[0] if coords else {}
    return {
        "title": data.get("title") or title,
        "extract": extract,
        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
        "coordinates": {"lat": coords["lat"], "lon": coords["lon"]} if "lat" in coords and "lon" in coords else None,
    }
