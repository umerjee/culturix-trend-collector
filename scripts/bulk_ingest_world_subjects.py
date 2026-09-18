"""Populate the World subject library from real Wikipedia and UNESCO data.

The run is deliberately resumable: every source is processed independently,
existing curated items are skipped by the ingestion service, and one failed
country/source does not stop the rest of the batch.

Default coverage is 20 high-volume/important World regions. Use a smaller
``--unesco-limit`` first if you want a quick initial library.

Examples:
    python scripts/bulk_ingest_world_subjects.py --unesco-limit 3 --max-items 2
    python scripts/bulk_ingest_world_subjects.py --only US,FR,JP
"""
import argparse
import logging
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

logger = logging.getLogger("culturix.bulk_ingest")

COUNTRIES = {
    "US": "United States",
    "CN": "China",
    "IN": "India",
    "JP": "Japan",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "GB": "United Kingdom",
    "MX": "Mexico",
    "BR": "Brazil",
    "CA": "Canada",
    "AU": "Australia",
    "TR": "Turkey",
    "KR": "South Korea",
    "SA": "Saudi Arabia",
    "EG": "Egypt",
    "GR": "Greece",
    "PT": "Portugal",
    "IR": "Iran",
}


def ingest_wikipedia(region: str, country: str, max_items: int) -> int:
    # These stable country-history pages give each region one broad,
    # encyclopedic source without guessing an article from search results.
    source = fetch_wikipedia_extract(f"History of {country}", full_text=True)
    if not source:
        logger.warning("Wikipedia source unavailable: %s", country)
        return 0
    session = SessionLocal()
    try:
        rows = ingest("wikipedia", region, source["extract"], session,
                      max_items=max_items, source_ref=source["title"], source_url=source.get("url"))
    finally:
        session.close()
    return len(rows)


def ingest_unesco(region: str, limit: int, max_items: int) -> int:
    created = 0
    for site in fetch_unesco_sites(region, limit=limit):
        source_ref = str(site.get("id_no") or site.get("title") or "")
        raw_text = unesco_source_text(site)
        if not source_ref or not raw_text:
            continue
        session = SessionLocal()
        try:
            created += len(ingest("unesco", region, raw_text, session,
                                  max_items=max_items, source_ref=source_ref,
                                  source_url=site.get("url")))
        finally:
            session.close()
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--unesco-limit", type=int, default=3, help="UNESCO sites per country (default: 3)")
    parser.add_argument("--max-items", type=int, default=2, help="Extracted items per source (default: 2)")
    parser.add_argument("--only", help="Comma-separated ISO-2 codes instead of all 20 countries")
    parser.add_argument("--source", choices=["both", "wikipedia", "unesco"], default="both", help="Source(s) to ingest")
    args = parser.parse_args()
    regions = [code.strip().upper() for code in args.only.split(",")] if args.only else list(COUNTRIES)
    unknown = [code for code in regions if code not in COUNTRIES]
    if unknown:
        raise SystemExit(f"Unknown region code(s): {', '.join(unknown)}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    totals = {"wikipedia": 0, "unesco": 0, "failed": 0}
    for index, region in enumerate(regions, 1):
        country = COUNTRIES[region]
        print(f"[{index}/{len(regions)}] {country} ({region})")
        try:
            if args.source == "unesco":
                raise StopIteration
            created = ingest_wikipedia(region, country, max(1, min(args.max_items, 5)))
            totals["wikipedia"] += created
            print(f"  Wikipedia: {created} new subject(s)")
        except StopIteration:
            pass
        except Exception:
            totals["failed"] += 1
            logger.exception("Wikipedia ingestion failed for %s", region)
        try:
            if args.source == "wikipedia":
                raise StopIteration
            created = ingest_unesco(region, max(1, min(args.unesco_limit, 10)), max(1, min(args.max_items, 5)))
            totals["unesco"] += created
            print(f"  UNESCO: {created} new subject(s)")
        except StopIteration:
            pass
        except Exception:
            totals["failed"] += 1
            logger.exception("UNESCO ingestion failed for %s", region)
    print(f"Complete: {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())