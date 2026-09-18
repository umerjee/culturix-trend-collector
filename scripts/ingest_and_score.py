"""Ingest real source material into the curated-item validation pipeline.

Examples:
    python scripts/ingest_and_score.py --wikipedia "Strait of Hormuz" --region IR
    python scripts/ingest_and_score.py --unesco --region IT --limit 10

This is deliberately a manual curator tool. It does not add curated material
to the scheduled trend collection sweep and never fabricates source text.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Titles come straight from Wikipedia/UNESCO and can contain any Unicode
# (macrons, CJK, accents); Windows' default cp1252 console crashes on them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(".env")

from app.collectors.unesco import fetch_unesco_sites, unesco_source_text
from app.collectors.wikipedia_extracts import fetch_wikipedia_extract
from app.db import SessionLocal
from app.services.culturix_ingestion import ingest


def _ingest_wikipedia(session, title: str, region: str | None, max_items: int) -> int:
    source = fetch_wikipedia_extract(title, full_text=True)
    if not source:
        print(f"No Wikipedia extract found for {title!r}.")
        return 0
    rows = ingest("wikipedia", region, source["extract"], session, max_items=max_items,
                  source_ref=source["title"], source_url=source.get("url"))
    print(f"Wikipedia {source['title']!r}: created {len(rows)} curated item(s).")
    return len(rows)


def _ingest_unesco(session, region: str | None, limit: int, max_items: int) -> int:
    sites = fetch_unesco_sites(region, limit=limit)
    total = 0
    for site in sites:
        source_ref = str(site.get("id_no") or site.get("title") or "")
        raw_text = unesco_source_text(site)
        if not source_ref or not raw_text:
            continue
        rows = ingest("unesco", region, raw_text, session, max_items=max_items, source_ref=source_ref,
                      source_url=site.get("url"))
        total += len(rows)
    print(f"UNESCO {region or 'all regions'}: created {total} curated item(s) from {len(sites)} site(s).")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wikipedia", metavar="TITLE", help="Fetch and curate one Wikipedia article")
    source.add_argument("--unesco", action="store_true", help="Fetch and curate UNESCO World Heritage sites")
    parser.add_argument("--region", help="ISO-2 region code, used for UNESCO filtering and item metadata")
    parser.add_argument("--limit", type=int, default=20, help="Maximum UNESCO sites to fetch")
    parser.add_argument("--max-items", type=int, default=5, help="Maximum extracted items per source")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        if args.wikipedia:
            _ingest_wikipedia(session, args.wikipedia, args.region, max(1, args.max_items))
        else:
            _ingest_unesco(session, args.region, max(1, min(args.limit, 100)), max(1, args.max_items))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())