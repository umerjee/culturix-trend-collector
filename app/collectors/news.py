"""Live top headlines per country, from Google News' public RSS edition for
that country — free, no key. Verified live 2026-09-18: 30-38 real headlines
per edition (FR, DE, JP, US), in the local language.

Used at generation time by app/services/region_daily_summary.py to compare
what the news is covering against what people are engaging with on social
platforms. Headlines are used as model input only and are not republished.
Not wired into orchestrator.py's scheduled sweep: it is a live lookup, not a
stored signal.

GDELT's free API (which also offers a per-country tone timeline) was tried
and rejected: it answered HTTP 429 to every request, even after a long pause.
"""
import logging
import re
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger("culturix.collectors.news")

_URL = "https://news.google.com/rss"
_HEADERS = {"User-Agent": "culturix-trend-collector/1.0 (contact: umer.ali79@gmail.com)"}

# Local-language edition where Google News offers one; anything else, or an
# edition that comes back nearly empty, falls back to the English edition.
_LOCAL_HL = {
    "FR": "fr", "DE": "de", "IT": "it", "ES": "es", "PT": "pt-PT", "BR": "pt-419", "JP": "ja",
    "KR": "ko", "MX": "es-419", "AR": "es-419", "CO": "es-419", "TR": "tr", "ID": "id",
    "VN": "vi", "TH": "th", "PL": "pl", "UA": "uk", "IL": "he", "EG": "ar", "SA": "ar", "AE": "ar",
}
# Countries with a genuine English edition. Asking for an English edition of
# any other country makes Google quietly serve the US one (Egypt returned the
# same BBC story as the US), which would put a foreign headline in a
# country's summary — so those return nothing instead.
_ENGLISH_EDITIONS = {"US", "GB", "CA", "AU", "IN", "NG", "KE", "ZA", "PH", "MY", "PK", "SG", "IE", "NZ", "GH", "IL", "ID"}
_MIN_ITEMS = 5


def _fetch(hl: str, region: str, lang: str) -> list[dict]:
    resp = httpx.get(
        _URL, params={"hl": hl, "gl": region, "ceid": f"{region}:{lang}"},
        headers=_HEADERS, timeout=10.0, follow_redirects=True,
    )
    resp.raise_for_status()
    items = []
    for item in ET.fromstring(resp.content).iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(f" - {source}")].rstrip()
        title = re.sub(r"\s+", " ", title)
        if title:
            items.append({"title": title[:200], "source": source or None})
    return items


def fetch_country_headlines(region: str, limit: int = 10) -> list[dict]:
    """[{"title", "source"}, ...] for a country's current top stories, or []
    on any failure — never raises, matching every other collector's fetch_*
    convention in this package."""
    region = (region or "").strip().upper()
    if len(region) != 2:
        return []
    attempts = []
    if region in _LOCAL_HL:
        attempts.append((_LOCAL_HL[region], _LOCAL_HL[region].split("-")[0]))
    if region in _ENGLISH_EDITIONS:
        attempts.append(("en", "en"))
    best: list[dict] = []
    for hl, lang in attempts:
        try:
            items = _fetch(hl, region, lang)
        except Exception as exc:
            logger.warning("News fetch failed for %s (%s): %s", region, hl, exc)
            continue
        if len(items) >= _MIN_ITEMS:
            return items[:limit]
        best = best or items
    return best[:limit]
