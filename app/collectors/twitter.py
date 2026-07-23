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

from app.collectors.region_codes import normalize_region

logger = logging.getLogger("culturix.collectors.twitter")

DEFAULT_QUERIES = [
    "trending now -is:retweet",
    "viral today -is:retweet",
    "breaking culture -is:retweet",
]

JINA_PROXY = "https://r.jina.ai/http://trends24.in/?geo={region}"
# Widened to match TikTok/YouTube's regional coverage (both tag US/GB/FR,
# YouTube also CA/AU) — Twitter was previously the dominant data source
# (~half of all trends) yet only ever tagged us/uk, meaning a profile
# targeting France/Canada/Australia alone (not "Global") could see every
# Twitter-sourced cluster hard-excluded by persona_mapper.py's region
# filter for having a resolved-but-non-matching region, on top of getting
# none of Twitter's volume as region-unknown (fail-open) content either.
TWITTER_REGIONS = ["us", "uk", "india", "japan", "france", "canada", "australia", "italy", "spain", "portugal", "global"]


def _collect_via_apify(queries: list[str] | None = None, max_items: int = 200) -> list[dict]:
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
        run = client.actor("apidojo/tweet-scraper").call(
            run_input={
                "searchTerms": qrs,
                "maxItems": max_items,
                "sort": "Latest",
                "lang": "",  # all languages
            }
        )
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


def _store_via_apify(queries: list[str] | None = None, max_items: int = 200) -> int:
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.language import detect_language, translate_to_english_if_needed

    signals = _collect_via_apify(queries, max_items)
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
                # region left unset (NULL) — this actor's search results aren't
                # tied to a single region/market the way tiktok.py/youtube.py's
                # per-region charts are.
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


def _fetch_via_proxy(region: str = "US") -> list[str]:
    """Scrapes trends24.in through the Jina.ai markdown proxy — free, no API
    key. Returns trend names extracted from the markdown numbered list."""
    import httpx
    import re

    try:
        geo_map = {
            "global": "US",  # trends24 doesn't use 'global' so use US as fallback
            "us": "US", "uk": "GB", "india": "IN", "japan": "JP",
            "france": "FR", "canada": "CA", "australia": "AU",
            "italy": "IT", "spain": "ES", "portugal": "PT",
        }
        geo_code = geo_map.get(region.lower(), "US")

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
    on failure. `region` only affects the proxy fallback — the Apify actor
    searches fixed DEFAULT_QUERIES rather than per-region terms."""
    if os.getenv("APIFY_API_TOKEN"):
        try:
            inserted = _store_via_apify()
            if inserted > 0:
                return inserted
        except Exception as e:
            logger.warning("Apify path failed, falling back to proxy: %s", e)

    return _store_via_proxy(region)
