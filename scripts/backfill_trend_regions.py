"""Backfill Trend.region only from embedded collector region metadata.

The collector payload is the source of truth here. This script deliberately
does not infer a country from language, title, URL, or engagement data.

Usage:
    python scripts/backfill_trend_regions.py          # report only
    python scripts/backfill_trend_regions.py --apply  # write safe mappings
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(".env")

_CANDIDATE_SQL = """
    SELECT platform, COUNT(*) AS rows_to_update
    FROM trends
    WHERE region IS NULL
      AND platform IN ('tiktok', 'pinterest', 'twitter')
      AND raw_json->>'region' ~ '^[A-Za-z]{2}$'
    GROUP BY platform
    ORDER BY platform
"""

_UPDATE_SQL = """
    UPDATE trends
    SET region = upper(trim(raw_json->>'region'))
    WHERE region IS NULL
      AND platform IN ('tiktok', 'pinterest', 'twitter')
      AND raw_json->>'region' ~ '^[A-Za-z]{2}$'
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Write the verified source-region mappings")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    # Force the driver explicitly — see app/db.py's own comment on the same fix: a bare
    # "postgresql://" left SQLAlchemy's dialect resolution to chance and broke live in CI
    # when it picked psycopg (v3, not installed) instead of psycopg2.
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        candidates = connection.execute(text(_CANDIDATE_SQL)).fetchall()
        total = sum(row.rows_to_update for row in candidates)
        print(f"Safe candidates: {total} row(s)")
        for row in candidates:
            print(f"  {row.platform}: {row.rows_to_update}")

        if args.apply and total:
            result = connection.execute(text(_UPDATE_SQL))
            print(f"Updated: {result.rowcount} row(s)")
        elif not args.apply:
            print("Dry run only. Re-run with --apply to write these mappings.")
        else:
            print("Nothing to update.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())