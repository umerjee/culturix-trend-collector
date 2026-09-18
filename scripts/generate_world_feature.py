"""Generates one World Feature end-to-end: a subject-centric public video
(a place/phenomenon/species is the star, character optional) for the
/world section — see app/models/toon.py's is_world_content docstring and
app/services/culturetoon_script.py::generate_world_script.

Deliberately manual/admin-triggered for v1 (per the World Features plan):
there is no automated "pick an interesting subject for region X" step —
region, subject and category are curated by a human via the CLI args
below. This script does the rest: pulls real region-filtered Trend rows
for factual grounding, optionally looks up a Culture row and/or a host
CharacterVariant, writes the ToonScript + Toon rows against the reserved
"World" CharacterBrand (seeded at app startup — see app/main.py's
lifespan()), then renders the video via the same production entry point
the interactive "Generate video" button uses.

Usage:
    python scripts/generate_world_feature.py \
        --region IR --region-label Iran --subject "The Strait of Hormuz" \
        --category place

    python scripts/generate_world_feature.py \
        --region "" --region-label "The Pacific Ocean" \
        --subject "Bioluminescent deep-sea creatures" --category species \
        --culture-name Japanese --duration 24

    python scripts/generate_world_feature.py --dry-run --region JP \
        --region-label Japan --subject "Mount Fuji" --category place
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(".env")

from app.db import SessionLocal  # noqa: E402
from app.models.character_brand import CharacterBrand  # noqa: E402
from app.models.character_variant import CharacterVariant  # noqa: E402
from app.models.culture import Culture  # noqa: E402
from app.models.toon import Toon  # noqa: E402
from app.models.toon_script import ToonScript  # noqa: E402
from app.models.trend import Trend  # noqa: E402
from app.collectors.region_codes import normalize_region  # noqa: E402
from app.services.culturetoon_script import generate_world_script, judge_script_comedy  # noqa: E402


def _serialize_culture(c: Culture) -> dict:
    return {
        "name": c.name,
        "humor_sensitivity": c.humor_sensitivity,
        "common_misunderstandings": c.common_misunderstandings,
        "positive_traits": c.positive_traits,
        "stereotypes_to_avoid": c.stereotypes_to_avoid,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", required=True, help="ISO-2 region code (matched against Trend.region), may be blank for a subject with no strong single-country tie")
    parser.add_argument("--region-label", required=True, help="Human-readable region name for the prompt/display, e.g. 'Iran' or 'The Pacific Ocean'")
    parser.add_argument("--subject", required=True, help="The subject itself, e.g. 'The Strait of Hormuz', 'A solar eclipse', 'Deep-sea bioluminescent creatures'")
    parser.add_argument("--category", default="place", choices=["place", "phenomenon", "species", "tech", "custom"])
    parser.add_argument("--culture-name", default=None, help="Culture.name to attach for cultural context, if one already exists in the library (see POST /api/culturetoons/cultures)")
    parser.add_argument("--host-variant-id", default=None, help="Optional CharacterVariant UUID to use as an on-screen regional host/narrator")
    parser.add_argument("--tone", default="informative", choices=["informative", "educational", "explainer", "inspirational",
                                                                    "funny", "dramatic", "satiric", "wholesome", "chaotic", "deadpan"])
    parser.add_argument("--num-shots", type=int, default=4)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--trend-limit", type=int, default=8, help="How many recent region-matching Trend rows to ground the script in")
    parser.add_argument("--owner-user-id", default=os.getenv("SUPERADMIN_USER_ID"),
                         help="Owner for the reserved 'World' brand if it doesn't exist yet — defaults to SUPERADMIN_USER_ID. "
                              "Only needed the first time this script runs; app/main.py's lifespan() seeds the same brand "
                              "on server startup too, but that requires SUPERADMIN_USER_ID to be set there, and this script "
                              "shouldn't have to depend on a server having been started first.")
    parser.add_argument("--dry-run", action="store_true", help="Generate and print the script, write nothing, render nothing")
    args = parser.parse_args()

    region_code = normalize_region(args.region) if args.region else None

    session = SessionLocal()
    try:
        world_brand = session.query(CharacterBrand).filter_by(name="World").order_by(CharacterBrand.created_at.asc()).first()
        if not world_brand and not args.dry_run:
            if not args.owner_user_id:
                raise SystemExit(
                    "No reserved 'World' CharacterBrand found, and no owner to create one with — "
                    "pass --owner-user-id, or set SUPERADMIN_USER_ID."
                )
            world_brand = CharacterBrand(
                user_id=args.owner_user_id, name="World",
                description="Subject-centric public content — places, phenomena, species — "
                             "organized by world region. See docs/culturix-video-pipeline.md.",
            )
            session.add(world_brand)
            session.commit()
            session.refresh(world_brand)
            print(f"Created reserved 'World' CharacterBrand: {world_brand.id}")

        trends = []
        if region_code:
            trend_rows = (
                session.query(Trend)
                .filter(Trend.region == region_code)
                .order_by(Trend.collected_at.desc())
                .limit(args.trend_limit)
                .all()
            )
            trends = [{"title": t.title, "content": t.content} for t in trend_rows]
        print(f"Grounding trends for region={region_code or '(none)'}: {len(trends)} found")

        culture = None
        if args.culture_name:
            culture_row = session.query(Culture).filter_by(name=args.culture_name).first()
            if not culture_row:
                print(f"WARNING: no Culture row named '{args.culture_name}' — proceeding without cultural context")
            else:
                culture = _serialize_culture(culture_row)

        host_variant = None
        if args.host_variant_id:
            host_variant = session.query(CharacterVariant).filter_by(id=args.host_variant_id).first()
            if not host_variant:
                raise SystemExit(f"--host-variant-id {args.host_variant_id} not found")
            print(f"Host: {host_variant.name}")
        else:
            print("Host: none (pure subject footage, voiceover narration)")

        print(f"Generating script for subject: {args.subject!r} ({args.category}, tone={args.tone})...")
        result = generate_world_script(
            region_code=region_code or "", region_label=args.region_label,
            subject_text=args.subject, subject_category=args.category,
            trends=trends, culture=culture, host_variant=host_variant,
            tone=args.tone, num_shots=args.num_shots, target_duration_seconds=args.duration,
        )
        judgment = judge_script_comedy(result)
        print(f"hook_line: {result.get('hook_line')}")
        print(f"shots: {len(result.get('shots') or [])}, total_duration_seconds: {result.get('total_duration_seconds')}")
        print(f"judge: score={judgment.get('comedy_score')} passes_bar={judgment.get('passes_bar')} feedback={judgment.get('feedback')}")

        if args.dry_run:
            print("\n--dry-run: nothing written, nothing rendered.")
            return 0

        script = ToonScript(
            brand_id=world_brand.id,
            character_variant_id=host_variant.id if host_variant else None,
            character_variant_ids=[str(host_variant.id)] if host_variant else None,
            hook_line=result.get("hook_line"),
            tone=args.tone,
            shots=result.get("shots"),
            total_duration_seconds=result.get("total_duration_seconds"),
            comedy_judgment=judgment,
            generation_source="ai",
            status="approved",
            is_world_content=True,
            subject_region=region_code,
            subject_text=args.subject,
            subject_category=args.category,
            culture_id=culture_row.id if args.culture_name and culture else None,
        )
        session.add(script)
        session.commit()
        session.refresh(script)
        print(f"ToonScript created: {script.id}")

        toon = Toon(
            brand_id=world_brand.id,
            character_variant_id=host_variant.id if host_variant else None,
            script_id=script.id,
            title=args.subject,
            status="idea",
            is_world_content=True,
            subject_region=region_code,
            subject_text=args.subject,
            subject_category=args.category,
        )
        session.add(toon)
        session.commit()
        session.refresh(toon)
        toon_id = str(toon.id)
        owner_user_id = str(world_brand.user_id)
        print(f"Toon created: {toon_id}")
    finally:
        session.close()

    print("Rendering via the real production entry point (same one the interactive 'Generate video' button uses)...")
    from app.services.culturetoon_selfhosted_video import generate_video_for_toon_selfhosted

    generate_video_for_toon_selfhosted(owner_user_id, toon_id)

    session = SessionLocal()
    try:
        toon = session.query(Toon).filter_by(id=toon_id).first()
        print(f"Done -- status={toon.status}, video_url={toon.final_video_url}, error={toon.generation_error}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
