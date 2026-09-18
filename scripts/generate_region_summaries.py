"""Generate the daily country briefs (calendar + trends) on demand or backfill
past days for the World time cursor.

    python scripts/generate_region_summaries.py --dry-run
    python scripts/generate_region_summaries.py --region FR
    python scripts/generate_region_summaries.py --days 14        # today + previous 13 days

Existing rows for a day are kept unless --force. --no-llm writes template-only
summaries (no LLM cost).
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Summaries can contain any Unicode (accents, CJK); Windows' default cp1252
# console crashes printing them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(".env")

from app.db import SessionLocal  # noqa: E402
from app.services.region_daily_summary import (  # noqa: E402
    gather_inputs, generate_region_summary, regions_to_summarize, template_summary,
)
from app.collectors.news import fetch_country_headlines  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", help="One ISO-2 region (default: every eligible region)")
    parser.add_argument("--days", type=int, default=1, help="How many days back to cover, ending today (default 1)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing summaries")
    parser.add_argument("--no-llm", action="store_true", help="Template-only, no LLM calls")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be generated; write nothing")
    args = parser.parse_args()

    today = datetime.utcnow().date()
    session = SessionLocal()
    try:
        # Oldest first: each day's stored mood becomes history for the next.
        for offset in reversed(range(max(1, args.days))):
            day = today - timedelta(days=offset)
            regions = [args.region.strip().upper()] if args.region else regions_to_summarize(session, day)
            print(f"== {day} — {len(regions)} region(s)")
            for region in regions:
                if args.dry_run:
                    inputs = gather_inputs(session, region, day, fetch_country_headlines(region) if day == today else [])
                    print(f"  {region}: {inputs['signal_count']} signals ({len(inputs['topics'])} usable topics), "
                          f"{len(inputs['events'])} calendar event(s), {len(inputs['headlines'])} headlines, "
                          f"baseline={'yes' if inputs['baseline'].get('enough') else 'no'}")
                    print(f"     template: {template_summary(inputs)}")
                    continue
                row = generate_region_summary(session, region, day, force=args.force, use_llm=not args.no_llm)
                print(f"  {region} [{row.source if row else 'skipped'}] {row.summary if row else ''}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
