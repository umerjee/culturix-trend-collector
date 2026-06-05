"""
run_pipeline.py -- full end-to-end pipeline runner + status reporter.

Usage (from project root, with venv active):
    python run_pipeline.py

Runs in order:
  1. Collect trends  (Twitter, TikTok, YouTube)
  2. Process embeddings
  3. Cluster trends
  4. Generate personas (clustered)
  5. Print a final status report
"""
import sys
import traceback
from datetime import datetime

DIVIDER = "=" * 60


def section(title):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def ok(msg):
    print(f"  [OK]   {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")


# -- 1. Collectors -------------------------------------------------------------

section("STEP 1 -- Collecting trends")

total_collected = 0

# Twitter
try:
    from app.collectors.twitter import store_twitter_trends, _get_bearer_from_env
    from app.collectors.twitter_fallback import store_twitter_trends_via_proxy

    if _get_bearer_from_env():
        try:
            n = store_twitter_trends("global")
            if n > 0:
                ok(f"Twitter (API):   {n} new trends")
                total_collected += n
            else:
                warn("Twitter (API): 0 new (duplicates or empty response)")
        except Exception as e:
            warn(f"Twitter API failed ({e}), trying proxy fallback...")
            n = store_twitter_trends_via_proxy("us")
            ok(f"Twitter (proxy): {n} new trends") if n else warn("Twitter proxy: 0 new")
            total_collected += n
    else:
        n = store_twitter_trends_via_proxy("us")
        ok(f"Twitter (proxy): {n} new trends") if n else warn("Twitter proxy: 0 new (no bearer token)")
        total_collected += n
except Exception as e:
    fail(f"Twitter collector crashed: {e}")
    traceback.print_exc()

# TikTok
try:
    from app.collectors.tiktok import store_tiktok_trends
    n = store_tiktok_trends(region="US")
    ok(f"TikTok:          {n} new trends") if n else warn("TikTok: 0 new (duplicates or API issue)")
    total_collected += n
except Exception as e:
    fail(f"TikTok collector crashed: {e}")
    traceback.print_exc()

# YouTube
try:
    from app.collectors.youtube import store_youtube_trends, fetch_youtube_trending
    probe = fetch_youtube_trending("US", limit=1)
    if probe:
        n = store_youtube_trends("US")
        ok(f"YouTube:         {n} new trends") if n else warn("YouTube: 0 new (duplicates)")
        total_collected += n
    else:
        warn("YouTube: API key missing or disabled -- skipping")
except Exception as e:
    fail(f"YouTube collector crashed: {e}")
    traceback.print_exc()

print(f"\n  -> Total new trends collected: {total_collected}")

# -- DB count ------------------------------------------------------------------

section("DB STATUS -- Trends in database")

try:
    from app.db import SessionLocal
    from app.models.trend import Trend
    session = SessionLocal()
    total_in_db = session.query(Trend).count()
    embedded_count = session.query(Trend).filter(Trend.embedding.isnot(None)).count()
    from sqlalchemy import func
    platform_counts = (
        session.query(Trend.platform, func.count(Trend.id))
        .group_by(Trend.platform)
        .all()
    )
    session.close()

    ok(f"Total trends in DB:    {total_in_db}")
    ok(f"Already embedded:      {embedded_count}")
    for platform, count in platform_counts:
        print(f"       {platform:<12} {count}")
except Exception as e:
    fail(f"Could not query DB: {e}")
    traceback.print_exc()

# -- 2. Embeddings -------------------------------------------------------------

section("STEP 2 -- Generating embeddings")

try:
    from app.embedding_processor import process_embeddings
    n = process_embeddings(limit=500)
    ok(f"Embedded {n} trends (new)") if n else warn("All trends already embedded (or no content)")
except Exception as e:
    fail(f"Embedding failed: {e}")
    traceback.print_exc()

# -- 3. Clustering -------------------------------------------------------------

section("STEP 3 -- Clustering")

try:
    from app.clustering_service import run_clustering
    result = run_clustering(limit=500, min_cluster_size=2)
    if "warning" in result:
        warn(result["warning"])
    else:
        ok(f"Clusters found:    {result['clusters']}")
        ok(f"Noise points:      {result['noise']}")
        ok(f"Trends processed:  {result['total_trends']}")
except Exception as e:
    fail(f"Clustering failed: {e}")
    traceback.print_exc()

# -- 4. Personas ---------------------------------------------------------------

section("STEP 4 -- Generating personas")

try:
    from app.personas import generate_clustered_personas
    result = generate_clustered_personas(limit=200, min_cluster_size=2)
    if "error" in result:
        fail(f"Persona generation error: {result['error']}")
    else:
        ok(f"Clusters processed: {result['clusters']}")
        ok(f"Personas created:   {result['personas_created']}")
except Exception as e:
    fail(f"Persona generation failed: {e}")
    traceback.print_exc()

# -- 5. Final report -----------------------------------------------------------

section("FINAL REPORT")

try:
    from app.db import SessionLocal
    from app.models.trend import Trend
    from app.models.cluster import Cluster
    from app.models.persona import Persona
    from sqlalchemy import func

    session = SessionLocal()

    trend_count   = session.query(Trend).count()
    embedded      = session.query(Trend).filter(Trend.embedding.isnot(None)).count()
    clustered     = session.query(Trend).filter(Trend.cluster_id.isnot(None)).count()
    cluster_count = session.query(Cluster).count()
    persona_count = session.query(Persona).count()

    session.close()

    print(f"  Trends total:      {trend_count}")
    print(f"  Embedded:          {embedded}")
    print(f"  Clustered:         {clustered}")
    print(f"  Clusters:          {cluster_count}")
    print(f"  Personas:          {persona_count}")
    print()

    if persona_count > 0:
        ok("Pipeline complete! Personas are ready.")
        print("\n  Start the API server with:")
        print("    uvicorn app.main:app --reload")
        print()
        print("  Key endpoints:")
        print("    GET  http://localhost:8000/trends/latest")
        print("    GET  http://localhost:8000/clusters")
        print("    GET  http://localhost:8000/personas")
        print("    GET  http://localhost:8000/recommendations")
        print("    GET  http://localhost:8000/search?q=<term>")
        print("    GET  http://localhost:8000/docs  (Swagger UI)")
    elif cluster_count > 0:
        warn("Clusters exist but no personas yet -- re-run Step 4 manually.")
    elif embedded > 0:
        warn("Embeddings exist but no clusters -- need more data (min_cluster_size=2).")
    else:
        warn("No embeddings yet -- check API keys and collector output above.")

except Exception as e:
    fail(f"Final report failed: {e}")
    traceback.print_exc()

print(f"\n{DIVIDER}\n")
