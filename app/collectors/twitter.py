"""Twitter/X collector — single canonical path, Apify actor primary,
trends24.in-via-Jina-proxy fallback.

Consolidated from three previously-divergent files (twitter.py's official
API path, twitter_fallback.py, twitter_apify.py) that formed two different
fallback chains depending on entry point. The official Twitter API v1.1
`trends/place.json` path was retired entirely — live-tested and confirmed
403 Forbidden ("limited v1.1 endpoints only... different access level
needed") on this account's current API tier, and even when it worked it
only returned bare trend names (no content/engagement/author), the same
shallow shape as the proxy fallback, for more fragility (a hand-rolled
raw-.env-file-parsing workaround) and no data-quality upside over the
Apify actor path below.
"""
import logging
import os
from datetime import datetime

from app.collectors.region_codes import normalize_region, SHARED_TARGET_REGIONS

logger = logging.getLogger("culturix.collectors.twitter")

DEFAULT_QUERIES = [
    "trending now -is:retweet",
    "viral today -is:retweet",
    "breaking culture -is:retweet",
]

JINA_PROXY = "https://r.jina.ai/http://trends24.in/?geo={region}"
# Widened 2026-09-18 to SHARED_TARGET_REGIONS (region_codes.py) — switched
# from lowercase country names to real ISO-2 codes to match that shared
# list directly rather than hand-maintaining 30+ new name aliases; trends24.in
# already expects ISO-2-shaped geo codes (see the old geo_map this replaced),
# so this is a like-for-like simplification, not a behavior change for the
# regions that already worked. "global" kept as a sentinel meaning "run every
# region in this list", not a real trends24.in geo value.
TWITTER_REGIONS = list(SHARED_TARGET_REGIONS) + ["global"]


# Additive, curated subset for the Apify geocode fix (see _store_via_apify_geocoded
# below) — the actor's broad DEFAULT_QUERIES call stays untouched for volume; this
# runs SEPARATELY, once per region, at real per-run Apify cost, so it's a smaller
# curated list, not the full SHARED_TARGET_REGIONS. Picks the 12 regions with zero
# Twitter coverage today (neither TikTok/YouTube already cover them well) that are
# highest product value. Values are (lat, long, radius) — Twitter API's own
# "lat,long,radiuskm" geocode convention — centered on each country's largest
# population center, not a literal country-wide bounding circle (a real
# simplification for large/elongated countries like Indonesia/Vietnam/Argentina;
# still meaningfully better than zero regional signal).
TWITTER_APIFY_GEOCODES: dict[str, tuple[float, float, str]] = {
    "TR": (39.93, 32.85, "500km"),   # Ankara
    "SA": (24.71, 46.68, "600km"),   # Riyadh
    "AE": (25.20, 55.27, "150km"),   # Dubai
    "ID": (-6.21, 106.85, "500km"),  # Jakarta
    "PH": (14.60, 120.98, "400km"),  # Manila
    "TH": (13.75, 100.50, "400km"),  # Bangkok
    "VN": (21.03, 105.85, "500km"),  # Hanoi
    "MX": (19.43, -99.13, "600km"),  # Mexico City
    "AR": (-34.60, -58.38, "500km"), # Buenos Aires
    "NG": (6.52, 3.38, "400km"),     # Lagos
    "ZA": (-26.20, 28.05, "500km"),  # Johannesburg
    "PL": (52.23, 21.01, "350km"),   # Warsaw
}


def _collect_via_apify(queries: list[str] | None = None, max_items: int = 200,
                        geocode: str | None = None) -> list[dict]:
    """geocode: optional "lat,long,radius" string — confirmed live against the
    actor's real input schema (apify.com/apidojo/tweet-scraper/input-schema) that
    it supports genuine geographic targeting, not just free-text search. None
    (the default) keeps today's broad, region-agnostic behavior."""
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("apify-client not installed — run: pip install apify-client")
        return []

    qrs = queries or DEFAULT_QUERIES
    client = ApifyClient(token)
    signals = []

    try:
        run_input = {
            "searchTerms": qrs,
            "maxItems": max_items,
            "sort": "Latest",
            "lang": "",  # all languages
        }
        if geocode:
            run_input["geocode"] = geocode
        run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
        if not run:
            logger.error("Twitter/Apify actor run returned no result")
            return []
        for item in client.dataset(run.default_dataset_id).iterate_items():
            signals.append({
                "external_id": str(item.get("id") or item.get("tweetId") or ""),
                "content_text": item.get("text") or item.get("fullText") or "",
                "author": item.get("author", {}).get("userName") if isinstance(item.get("author"), dict) else item.get("authorName"),
                "url": item.get("url") or f"https://x.com/i/web/status/{item.get('id')}",
                "likes": int(item.get("likeCount") or item.get("favoriteCount") or 0),
                "comments": int(item.get("replyCount") or 0),
                "shares": int(item.get("retweetCount") or 0),
                "views": int(item.get("viewCount") or 0),
                "language": item.get("lang") or "en",
            })
        logger.info("Collected %d tweets via Apify", len(signals))
    except Exception as e:
        logger.error("Twitter/Apify collection failed: %s", e)

    return signals


def _insert_apify_signals(signals: list[dict], region: str | None = None) -> int:
    """Shared insert path for both _store_via_apify (region=None, broad/
    volume call) and _store_via_apify_geocoded (region set, per-country
    geocode call) — same row shape either way, only whether `region` gets
    tagged differs."""
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.language import detect_language, translate_to_english_if_needed

    if not signals:
        return 0

    session = SessionLocal()
    inserted = 0
    try:
        for s in signals:
            if not s.get("external_id"):
                continue
            exists = session.query(Trend).filter_by(
                platform="twitter", external_id=s["external_id"]
            ).first()
            if exists:
                continue
            lang = detect_language(s["content_text"])
            translated = translate_to_english_if_needed(s["content_text"], lang)
            trend = Trend(
                platform="twitter",
                external_id=s["external_id"],
                title=s["content_text"][:200],
                content=s["content_text"],
                translated_content=translated,
                language=lang,
                url=s.get("url"),
                author=s.get("author"),
                likes=s.get("likes"),
                comments=s.get("comments"),
                views=s.get("views"),
                raw_json=s,
                region=normalize_region(region) if region else None,
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


def _store_via_apify(queries: list[str] | None = None, max_items: int = 200) -> int:
    # region left unset (NULL) — this broad call's search results aren't
    # tied to a single region/market the way tiktok.py/youtube.py's
    # per-region charts (or _store_via_apify_geocoded below) are.
    return _insert_apify_signals(_collect_via_apify(queries, max_items))


def _store_via_apify_geocoded(regions: dict[str, tuple[float, float, str]] | None = None,
                               max_items: int = 50) -> int:
    """Additive fix for _store_via_apify's region gap (see that function's
    comment) — one extra Apify actor run per region in `regions` (default
    TWITTER_APIFY_GEOCODES, a deliberately small curated subset: this is a
    real per-run cost multiplier, not a free list expansion like TikTok/
    YouTube/Google Trends). Each run's results get tagged with the region
    that produced them, unlike the broad call."""
    total = 0
    for region, (lat, lon, radius) in (regions or TWITTER_APIFY_GEOCODES).items():
        geocode = f"{lat},{lon},{radius}"
        signals = _collect_via_apify(max_items=max_items, geocode=geocode)
        total += _insert_apify_signals(signals, region=region)
    return total


def _fetch_via_proxy(region: str = "US") -> list[str]:
    """Scrapes trends24.in through the Jina.ai markdown proxy — free, no API
    key. Returns trend names extracted from the markdown numbered list."""
    import httpx
    import re

    try:
        # TWITTER_REGIONS now holds real ISO-2 codes directly (see that
        # constant's own comment), but POST /collect/twitter (app/main.py)
        # is a manual admin endpoint that can still be called with a legacy
        # lowercase full name (e.g. ?region=india) — normalize_region()
        # already has the alias table for exactly that (uk->GB, india->IN,
        # etc.), and passes a bare ISO-2 code through unchanged, so this
        # handles both shapes correctly instead of the raw .upper() this
        # replaced (which silently produced wrong trends24.in geo values
        # like "INDIA" for legacy name input). "global" (and any unmapped
        # input) normalizes to None -> falls back to US, matching the old
        # geo_map's own default-to-US behavior.
        geo_code = normalize_region(region) or "US"

        resp = httpx.get(JINA_PROXY.format(region=geo_code), timeout=20.0)
        if resp.status_code != 200:
            return []

        # Extract numbered items from markdown (e.g., "1.   [Trend Name](url)")
        matches = re.findall(r'^\d+\.\s+\[([^\]]+)\]', resp.text, re.MULTILINE)
        return [m.strip() for m in matches[:30] if m.strip() and len(m.strip()) > 1]
    except Exception as e:
        logger.warning("Twitter proxy fetch failed for region %s: %s", region, e)
        return []


def _store_via_proxy(region: str = "us") -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.language import detect_language

    regions = TWITTER_REGIONS if region in ("us", "global") else [region]
    session = SessionLocal()
    inserted = 0

    try:
        seen_in_run: set[str] = set()
        for r in regions:
            for name in _fetch_via_proxy(r):
                key = name.lower().strip()
                if key in seen_in_run:
                    continue
                seen_in_run.add(key)

                exists = session.query(Trend).filter_by(platform="twitter", external_id=name).first()
                if exists:
                    continue

                lang = detect_language(name)
                trend = Trend(
                    platform="twitter",
                    external_id=name,
                    url=f"https://twitter.com/search?q={name.replace('#', '')}",
                    title=name,
                    content=name,
                    translated_content=None,
                    language=lang,
                    author=None,
                    likes=None,
                    comments=None,
                    posted_at=datetime.utcnow(),
                    raw_json={"source": "trends24.in via jina.ai proxy", "region": r},
                    region=normalize_region(r),
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


def store_twitter_trends(region: str = "global") -> int:
    """Single entry point for both the scheduled orchestrator and the manual
    /collect/twitter route. Tries the Apify actor first (richer data: real
    tweet content, author, engagement) when APIFY_API_TOKEN is set; falls
    back to the free trends24.in proxy (bare trend names only) otherwise or
    on failure. `region` only affects the proxy fallback — the broad Apify
    call searches fixed DEFAULT_QUERIES rather than per-region terms.

    Also runs the geocoded Apify sweep (_store_via_apify_geocoded) as an
    ADDITIVE step whenever Apify is configured, regardless of whether the
    broad call found anything — this is the actual region-tagging fix for
    Apify's dominant path (see _store_via_apify's own comment on why it
    leaves region NULL), a real per-run cost on top of the broad call, not
    a replacement for it."""
    if os.getenv("APIFY_API_TOKEN"):
        try:
            inserted = _store_via_apify()
        except Exception as e:
            logger.warning("Apify broad path failed: %s", e)
            inserted = 0
        try:
            inserted += _store_via_apify_geocoded()
        except Exception as e:
            logger.warning("Apify geocoded path failed: %s", e)
        if inserted > 0:
            return inserted

    return _store_via_proxy(region)
