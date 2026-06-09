import os, sys, datetime

os.environ['DATABASE_URL'] = 'postgresql://postgres:gRFwohDiatCvgUOhdGmjrhaFXIFQjAYE@zephyr.proxy.rlwy.net:56811/railway'
os.environ['VOYAGE_API_KEY'] = 'pa-ij3BM22kEQub9sg6gpGezoOzsPW7vjHd0SkoMPwwRM4'
os.environ['TWITTER_BEARER_TOKEN'] = 'AAAAAAAAAAAAAAAAAAAAAHOa9wEAAAAAH2wDtp3wfazvSwm5%2BXFHhsudbKI%3DoqEcgzhgwBgc3vsIyFBfMDCj73aCLxKTzpr9euzaaVBRHwNMJP'
os.environ['YOUTUBE_API_KEY'] = 'AIzaSyDMpzuh8_qu0A3QWMTeky8ehQ2_mJLUjzk'
os.environ['ANTHROPIC_API_KEY'] = os.getenv('ANTHROPIC_API_KEY', '')
os.environ['DEEPSEEK_API_KEY'] = 'sk-abc2c9e628b742579926863d6dcb92da'
os.environ['QDRANT_URL'] = 'https://d897d30c-8b42-4cf6-9c44-74031d8408cf.eu-central-1-0.aws.cloud.qdrant.io'
os.environ['QDRANT_API_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6YjFjMTU1YjQtMTZmZi00MmE3LTk1NWUtOGI3ZjZiZDQ1OTdhIn0.IzLX0-qbgAzJiLJSpyR5jPDXfSSqXuMUqY3Zx0C9PUU'

import httpx
from app.db import SessionLocal
from app.models.trend import Trend
from app.language import detect_language, translate_to_english_if_needed

results = {}

# --- YouTube (multi-region) ---
from app.collectors.youtube import store_youtube_trends
for region in ['US', 'GB', 'FR', 'CA', 'NG', 'ZA']:
    try:
        n = store_youtube_trends(region, limit=30)
        results[f'youtube_{region}'] = n
        print(f'YouTube {region}: {n}')
    except Exception as e:
        results[f'youtube_{region}'] = 0
        print(f'YouTube {region} error: {e}')

# --- Twitter fallback (multi-region) ---
from app.collectors.twitter_fallback import store_twitter_trends_via_proxy
for region in ['global', 'united-states', 'united-kingdom', 'france', 'canada']:
    try:
        n = store_twitter_trends_via_proxy(region)
        results[f'twitter_{region}'] = n
        print(f'Twitter {region}: {n}')
    except Exception as e:
        results[f'twitter_{region}'] = 0
        print(f'Twitter {region} error: {e}')

# --- Reddit via RSS (no auth required) ---
session = SessionLocal()
reddit_inserted = 0
subreddits = ['all', 'technology', 'worldnews', 'entertainment', 'fashion',
              'streetwear', 'hiphopheads', 'malefashionadvice', 'sneakers',
              'beauty', 'MakeupAddiction', 'gaming', 'sports']
for sub in subreddits:
    try:
        resp = httpx.get(
            f'https://www.reddit.com/r/{sub}/top.json?t=day&limit=25',
            headers={'User-Agent': 'Mozilla/5.0 AppleWebKit/537.36 Safari/537.36'},
            timeout=10, follow_redirects=True
        )
        if resp.status_code != 200:
            print(f'Reddit r/{sub}: HTTP {resp.status_code}')
            continue
        posts = resp.json()['data']['children']
        for p in posts:
            d = p['data']
            if session.query(Trend).filter_by(external_id=d['id']).first():
                continue
            content = f"{d.get('title', '')}\n{d.get('selftext', '')}".strip()[:500]
            lang = detect_language(content)
            translated = translate_to_english_if_needed(content, lang)
            trend = Trend(
                platform='reddit', external_id=d['id'],
                content=translated, author=d.get('author', ''),
                url=f"https://reddit.com{d.get('permalink', '')}",
                likes=d.get('ups', 0), comments=d.get('num_comments', 0),
                language='en', collected_at=datetime.datetime.utcnow()
            )
            session.add(trend)
            reddit_inserted += 1
        session.commit()
        print(f'Reddit r/{sub}: ok')
    except Exception as e:
        print(f'Reddit r/{sub} error: {e}')

session.close()
results['reddit'] = reddit_inserted
print(f'Reddit total inserted: {reddit_inserted}')

# --- Final count ---
s = SessionLocal()
total = s.query(Trend).count()
s.close()
print(f'\nTotal trends in DB: {total}')
print('Collection complete.')
