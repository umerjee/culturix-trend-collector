"""UNESCO World Heritage site fetcher — real, free, no-auth data via the
official UNESCO DataHub API (data.unesco.org). Confirmed live before this
was written: 1,273 real sites, with `iso_codes` mapping directly onto this
app's own ISO-2 region vocabulary (app.collectors.region_codes) — no fuzzy
country-name matching needed.

Raw text source for app/services/culturix_ingestion.py, same posture as
wikipedia_extracts.py — a curator-triggered, on-demand pull (a region's
sites), not wired into app/collectors/orchestrator.py's scheduled sweep:
this dataset barely changes, there's no "trending" signal to poll for.
"""
import logging

import httpx

logger = logging.getLogger("culturix.collectors.unesco")

_BASE = "https://data.unesco.org/api/explore/v2.1/catalog/datasets/whc001/records"


def fetch_unesco_sites(region_code: str | None = None, limit: int = 20) -> list[dict]:
    """Returns up to `limit` real World Heritage sites, optionally filtered
    to one ISO-2 region code (matched against the dataset's own `iso_codes`
    field). [] on any failure — never raises, matching every other
    collector's fetch_* convention in this package."""
    params: dict = {"limit": max(1, min(limit, 100))}
    if region_code:
        # iso_codes is a multi-value field (e.g. transboundary sites list
        # several) — ODSQL's `in` operator on that field name.
        params["where"] = f'iso_codes in ("{region_code.strip().upper()}")'
    try:
        resp = httpx.get(_BASE, params=params, timeout=15.0)
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        logger.warning("UNESCO fetch failed (region=%s): %s", region_code, e)
        return []

    sites = []
    for r in results:
        sites.append({
            "id_no": r.get("id_no"),
            "title": r.get("name_en"),
            "description": r.get("short_description_en") or r.get("description_en") or "",
            "category": r.get("category"),  # Cultural | Natural | Mixed
            "date_inscribed": r.get("date_inscribed"),
            "iso_codes": r.get("iso_codes") or [],
            "states_names": r.get("states_names"),
            "region": r.get("region"),
            "coordinates": r.get("coordinates"),
            "url": f"https://whc.unesco.org/en/list/{r['id_no']}" if r.get("id_no") else None,
        })
    return sites


def unesco_source_text(site: dict, enrich: bool = True) -> str:
    """Raw text for one site: UNESCO's own name/description/category, plus —
    when a confidently-matching article exists — the Wikipedia article body.
    UNESCO's description is ~500 characters, too thin for a video to hook on;
    the Wikipedia text supplies the concrete detail. Sections are labeled so
    the provenance of every fact stays auditable in the stored raw_text."""
    parts = [v for v in (site.get("title"), site.get("description"), site.get("category")) if v]
    text = "\n".join(parts)
    if enrich and site.get("title"):
        from app.collectors.wikipedia_extracts import find_wikipedia_article
        article = find_wikipedia_article(site["title"])
        if article:
            text += f"\n\nWikipedia article \"{article['title']}\" ({article.get('url')}):\n{article['extract']}"
    return text
