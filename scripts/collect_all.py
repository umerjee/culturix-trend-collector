import os, sys, datetime

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

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
