"""Backfill curated_items.source_url for rows ingested before that column existed.

Only fills what is derivable with certainty from source_ref (never guesses):
  - UNESCO rows: source_ref is "<id_no>:<title>" -> https://whc.unesco.org/en/list/<id_no>
  - Wikipedia rows: source_ref is "<article title>:<item title>". Only the bulk
    ingest's fixed "History of <country>" article pattern is unambiguous.
Idempotent; --dry-run prints without writing.

    python scripts/backfill_curated_source_urls.py --dry-run
"""
import argparse
import os
import re
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Titles come straight from Wikipedia/UNESCO and can contain any Unicode
# (macrons, CJK, accents); Windows' default cp1252 console crashes on them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(".env")

from app.db import SessionLocal  # noqa: E402
from app.models.curated_item import CuratedItem  # noqa: E402

_HISTORY_OF = re.compile(r"^(History of [^:]+):")


def derive_source_url(source_type: str, source_ref: str | None) -> str | None:
    ref = source_ref or ""
    if source_type == "unesco":
        head = ref.split(":", 1)[0]
        return f"https://whc.unesco.org/en/list/{head}" if head.isdigit() else None
    if source_type == "wikipedia":
        match = _HISTORY_OF.match(ref)
        return f"https://en.wikipedia.org/wiki/{quote(match.group(1).replace(' ', '_'))}" if match else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        rows = session.query(CuratedItem).filter(CuratedItem.source_url.is_(None)).all()
        filled = 0
        for row in rows:
            url = derive_source_url(row.source_type, row.source_ref)
            if url:
                filled += 1
                print(f"{'would set' if args.dry_run else 'set'} {row.source_type:9} {row.title[:50]!r} -> {url}")
                if not args.dry_run:
                    row.source_url = url
        if not args.dry_run:
            session.commit()
        print(f"{filled} of {len(rows)} rows without a source_url are derivable.")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
