"""Publishes an EXISTING, already-rendered Toon onto the public /world map —
no regeneration, just flips is_world_content=True and sets the subject_*
fields on both the Toon and its ToonScript. See app/models/toon.py's
is_world_content docstring.

DO NOT use this on the old character-first Toons (the ones made before the
2026-09-18 region-first pivot — see docs/culturix-video-pipeline.md and the
CultureToons dashboard's existing brand/character flow). Confirmed live
2026-09-18: publishing one of these (a 3-character kitchen scene) to World
was wrong, not because of a bad region tag, but because that whole
generation approach was already judged not production-quality — publishing
it just puts the same low-quality content on a second surface. This script
is for Toons created under the NEW region-first approach once that exists
(a region/subject drives the script, character is an optional thematic
host) — there is currently no existing Toon in the DB that qualifies.

Usage:
    python scripts/publish_toon_to_world.py \
        --toon-id 39e428e5-1510-4d65-8665-b47f522d8ac5 \
        --region CH \
        --subject "Three friends debate cooking hacks across cultures" \
        --category place

    python scripts/publish_toon_to_world.py --dry-run \
        --toon-id <id> --region JP --subject "..." --category genz
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(".env")

from app.db import SessionLocal  # noqa: E402
from app.models.toon import Toon  # noqa: E402
from app.models.toon_script import ToonScript  # noqa: E402
from app.models.trend import Trend  # noqa: E402
from app.collectors.region_codes import normalize_region  # noqa: E402

# Reuses the exact same platform-mix heuristic as generate_world_feature.py
# — kept in sync manually (small enough not to warrant a shared module yet;
# revisit if a third caller needs it).
from generate_world_feature import _suggest_category_from_trends  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--toon-id", required=True, help="UUID of an existing, ready Toon (must have a final_video_url)")
    parser.add_argument("--region", required=True, help="ISO-2 region code, may be blank for no strong single-country tie")
    parser.add_argument("--subject", required=True, help="What this Feature is about, for World's subject_text (e.g. the premise/hook, in your own words)")
    parser.add_argument("--category", default=None, choices=["place", "phenomenon", "species", "tech", "genz", "custom"],
                         help="Omit to let the region's real trend-platform mix suggest 'genz' when TikTok-dominated, same as generate_world_feature.py")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change, write nothing")
    args = parser.parse_args()

    region_code = normalize_region(args.region) if args.region else None

    session = SessionLocal()
    try:
        toon = session.query(Toon).filter_by(id=args.toon_id).first()
        if not toon:
            raise SystemExit(f"Toon {args.toon_id} not found")
        if toon.status != "ready" or not toon.final_video_url:
            raise SystemExit(f"Toon {args.toon_id} is not ready (status={toon.status}, has_video={bool(toon.final_video_url)})")
        if toon.is_world_content:
            print(f"Note: toon {args.toon_id} is already is_world_content=True — this will overwrite its subject_* fields.")

        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        if not script:
            raise SystemExit(f"Toon {args.toon_id}'s script is missing")

        category = args.category
        if not category:
            trend_rows = []
            if region_code:
                trend_rows = (
                    session.query(Trend)
                    .filter(Trend.region == region_code)
                    .order_by(Trend.collected_at.desc())
                    .limit(8)
                    .all()
                )
            suggested = _suggest_category_from_trends(trend_rows)
            category = suggested or "place"
            print(f"No --category given — {'trend-signal suggestion' if suggested else 'no strong platform signal, defaulting'}: {category}")

        print(f"Publishing toon {toon.id} ({toon.title!r}) to World: region={region_code}, category={category}")
        print(f"  subject: {args.subject}")

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            return 0

        for obj in (toon, script):
            obj.is_world_content = True
            obj.subject_region = region_code
            obj.subject_text = args.subject
            obj.subject_category = category
        session.commit()
        print(f"Done — toon_id={toon.id} is now live on /world/region/{region_code or '(none)'}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
