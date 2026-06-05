import httpx
import re
from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language, translate_to_english_if_needed
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


def store_twitter_trends_via_proxy(region="US"):
    """
    Store Twitter trends fetched via Jina proxy fallback.
    """
    session = SessionLocal()
    try:
        items = fetch_twitter_trending_via_proxy(region)
    except Exception:
        session.close()
        return 0

    inserted = 0
    for name in items:
        # Skip if already stored
        exists = session.query(Trend).filter_by(platform="twitter", external_id=name).first()
        if exists:
            continue

        lang = detect_language(name)
        translated = translate_to_english_if_needed(name, lang)

        trend = Trend(
            platform="twitter",
            external_id=name,
            url=f"https://twitter.com/search?q={name.replace('#','')}",
            title=name,
            content=name,
            translated_content=translated,
            language=lang,
            author=None,
            likes=None,
            comments=None,
            posted_at=datetime.utcnow(),
            raw_json={"source": "trends24.in via jina.ai proxy"},
        )

        session.add(trend)
        inserted += 1

    session.commit()
    session.close()
    return inserted
