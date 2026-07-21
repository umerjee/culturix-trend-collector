import httpx
import re
from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language
from app.collectors.region_codes import normalize_region
from datetime import datetime
from urllib.parse import unquote_plus

JINA_PROXY = "https://r.jina.ai/http://trends24.in/?geo={region}"

def fetch_twitter_trending_via_proxy(region="US"):
    """
    Fallback method that scrapes trends24.in through the Jina.ai markdown proxy.
    Returns list of trend names extracted from the markdown numbered list.
    """
    try:
        # Map friendly names to geo codes
        geo_map = {
            "global": "US",  # trends24 doesn't use 'global' so use US as fallback
            "us": "US",
            "uk": "GB",
            "india": "IN",
            "japan": "JP",
        }
        geo_code = geo_map.get(region.lower(), "US")
        
        url = JINA_PROXY.format(region=geo_code)
        resp = httpx.get(url, timeout=20.0)
        
        if resp.status_code != 200:
            return []
        
        text = resp.text
        
        # Extract numbered items from markdown (e.g., "1.   [Trend Name](url)")
        # Pattern: number, dot, spaces, bracket link text
        pattern = r'^\d+\.\s+\[([^\]]+)\]'
        matches = re.findall(pattern, text, re.MULTILINE)
        
        # Clean up and return first 30
        trends = []
        for match in matches[:30]:
            clean = match.strip()
            if clean and len(clean) > 1:  # Skip very short strings
                trends.append(clean)
        
        return trends
    except Exception as e:
        print(f"Error fetching twitter via proxy: {e}")
        return []


TWITTER_REGIONS = ["us", "uk", "india", "japan", "global"]


def store_twitter_trends_via_proxy(region="us"):
    """Fetch Twitter trends for multiple regions to surface non-US viral signals."""
    regions = TWITTER_REGIONS if region in ("us", "global") else [region]
    session = SessionLocal()
    inserted = 0

    try:
        seen_in_run: set[str] = set()
        for r in regions:
            try:
                items = fetch_twitter_trending_via_proxy(r)
            except Exception:
                continue

            for name in items:
                # Deduplicate within this run (same trend may trend in multiple regions)
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
