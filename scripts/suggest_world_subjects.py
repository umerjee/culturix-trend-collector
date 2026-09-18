"""Suggests candidate World Feature subjects for a region, grounded in real
trend data — curator-review only, does NOT create or write anything. Cuts
down the time spent staring at raw Trend rows trying to invent an angle;
the curator still picks what actually gets made via
scripts/generate_world_feature.py (or discards every suggestion).

Usage:
    python scripts/suggest_world_subjects.py --region JP --region-label Japan

    # Sweep every region that currently has enough trend volume to ground
    # a suggestion in, instead of naming one:
    python scripts/suggest_world_subjects.py --all
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Suggestions/rationales come straight from an LLM and can contain any
# Unicode content (accents, CJK, em-dashes, etc.) — Windows' default
# console codepage (cp1252) crashes on anything outside it. Force UTF-8
# with a safe fallback rather than losing a real suggestion to a print
# crash after the (real, billed) LLM call already succeeded.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(".env")

from app.db import SessionLocal  # noqa: E402
from app.models.trend import Trend  # noqa: E402
from app.collectors.region_codes import normalize_region  # noqa: E402
from app.services.culturetoon_script import suggest_world_subjects_from_trends  # noqa: E402

# Same friendly-label convention as the rest of this codebase's region
# lists — not exhaustive, just enough to print something readable for
# --all; falls back to the bare code for anything not listed here.
_REGION_LABELS = {
    "US": "the United States", "GB": "the United Kingdom", "FR": "France", "DE": "Germany",
    "IT": "Italy", "ES": "Spain", "PT": "Portugal", "CA": "Canada", "AU": "Australia",
    "JP": "Japan", "KR": "South Korea", "IN": "India", "BR": "Brazil", "TR": "Turkey",
    "SA": "Saudi Arabia", "AE": "the UAE", "IL": "Israel", "NG": "Nigeria", "ZA": "South Africa",
    "EG": "Egypt", "KE": "Kenya", "ID": "Indonesia", "PH": "the Philippines", "TH": "Thailand",
    "VN": "Vietnam", "MY": "Malaysia", "MX": "Mexico", "AR": "Argentina", "CO": "Colombia",
    "CL": "Chile", "PL": "Poland", "UA": "Ukraine", "PK": "Pakistan", "CN": "China",
}


def _fetch_trends(session, region_code: str, limit: int = 15) -> list:
    rows = (
        session.query(Trend)
        .filter(Trend.region == region_code)
        .order_by(Trend.collected_at.desc())
        .limit(limit)
        .all()
    )
    return [{"title": t.title, "content": t.content} for t in rows]


def _print_suggestions(region_code: str, region_label: str, suggestions: list) -> None:
    print(f"\n=== {region_label} ({region_code}) ===")
    if not suggestions:
        print("  No well-grounded suggestions — not enough real trend material, or the LLM call failed.")
        return
    for s in suggestions:
        print(f"  [{s.get('subject_category', '?')}] {s.get('subject_text', '?')}")
        print(f"    {s.get('rationale', '')}")
        print(f"    -> python scripts/generate_world_feature.py --region {region_code} "
              f"--region-label \"{region_label}\" --subject \"{s.get('subject_text', '')}\" "
              f"--category {s.get('subject_category', 'place')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", help="ISO-2 region code to suggest for")
    parser.add_argument("--region-label", help="Human-readable label (defaults to a built-in lookup, or the code itself)")
    parser.add_argument("--all", action="store_true", help="Sweep every region with enough trend volume to suggest from")
    parser.add_argument("--min-trends", type=int, default=5, help="Skip a region with fewer than this many recent trend rows (--all only)")
    args = parser.parse_args()

    if not args.region and not args.all:
        raise SystemExit("Pass --region CODE or --all")

    session = SessionLocal()
    try:
        if args.all:
            from sqlalchemy import func
            counts = (
                session.query(Trend.region, func.count(Trend.id))
                .filter(Trend.region.isnot(None))
                .group_by(Trend.region)
                .having(func.count(Trend.id) >= args.min_trends)
                .all()
            )
            print(f"Sweeping {len(counts)} regions with >= {args.min_trends} recent trend rows...")
            for region_code, _count in sorted(counts, key=lambda c: -c[1]):
                label = _REGION_LABELS.get(region_code, region_code)
                trends = _fetch_trends(session, region_code)
                suggestions = suggest_world_subjects_from_trends(label, trends)
                _print_suggestions(region_code, label, suggestions)
        else:
            region_code = normalize_region(args.region) or args.region.upper()
            label = args.region_label or _REGION_LABELS.get(region_code, region_code)
            trends = _fetch_trends(session, region_code)
            print(f"Grounding on {len(trends)} recent trend rows for {label}...")
            suggestions = suggest_world_subjects_from_trends(label, trends)
            _print_suggestions(region_code, label, suggestions)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
