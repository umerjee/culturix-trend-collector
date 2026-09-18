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
from app.services.culturetoon_script import generate_world_script, judge_script_comedy, select_thematic_host  # noqa: E402


# Platforms whose userbase skews meaningfully younger than the others this
# app collects from (Reddit/Twitter/YouTube/Google Trends/Xiaohongshu) —
# TikTok is the one clear, real, already-collected signal for "this trend
# data leans Gen-Z," not a fabricated demographic field. A real signal from
# real Trend rows, not a guess — see app/collectors/*.py for what each
# collector tags Trend.platform as.
_YOUNG_SKEWING_PLATFORMS = {"tiktok"}


def _suggest_category_from_trends(trend_rows: list) -> "str | None":
    """Suggests 'genz' when the region's own grounding trends (the same
    rows generate_world_script uses for factual context) are TikTok-
    dominated. Returns None — no suggestion — when there isn't enough
    signal (too few rows, or no clear platform majority), so a low-
    confidence guess never overrides the admin's own judgment silently;
    see main()'s explicit-vs-default handling below."""
    if len(trend_rows) < 3:
        return None
    young = sum(1 for t in trend_rows if (t.platform or "").lower() in _YOUNG_SKEWING_PLATFORMS)
    share = young / len(trend_rows)
    if share >= 0.5:
        return "genz"
    return None


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
    parser.add_argument("--category", default=None, choices=["place", "phenomenon", "species", "tech", "genz", "custom"],
                         help="One merged filter tag covering both what the Feature is about (place/phenomenon/species/tech) "
                              "and who it's likely to resonate with (genz) — a curation/discovery tag only, does not change "
                              "how the script is written (always tone=informative unless --tone overrides it). Omit to let "
                              "the region's real trend-platform mix suggest 'genz' when TikTok-dominated (falls back to "
                              "'place' with no strong signal) — see _suggest_category_from_trends.")
    parser.add_argument("--culture-name", default=None, help="Culture.name to attach for cultural context, if one already exists in the library (see POST /api/culturetoons/cultures)")
    parser.add_argument("--era-label", default=None, help="Historical era this Feature is about, e.g. 'French Revolution' — separate from real trend data (there is none pre-June 2026); powers the World map time-cursor's historical zone")
    parser.add_argument("--era-year", type=int, default=None, help="Representative year for --era-label, e.g. 1789 — used for sorting/filtering, required for the Feature to show up in an era-range query")
    parser.add_argument("--host-variant-id", default=None, help="Optional CharacterVariant UUID to use as an on-screen regional host/narrator — wins outright over auto-selection below")
    parser.add_argument("--no-host", action="store_true", help="Explicitly skip auto-selecting a thematic host — pure subject footage, no character. Without this flag, omitting --host-variant-id tries auto-selection first (see select_thematic_host).")
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
        trend_rows = []
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

        suggested_category = _suggest_category_from_trends(trend_rows)
        if args.category:
            category = args.category
            if suggested_category and suggested_category != category:
                print(f"Note: trend platform mix suggests category '{suggested_category}', using your explicit --category '{category}' instead")
        else:
            category = suggested_category or "place"
            print(f"No --category given — {'trend-signal suggestion' if suggested_category else 'no strong platform signal, defaulting'}: {category}")

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
            print(f"Host: {host_variant.name} (explicit --host-variant-id)")
        elif args.no_host:
            print("Host: none (--no-host, pure subject footage, voiceover narration)")
        else:
            host_variant = select_thematic_host(session, category, args.tone)
            if host_variant:
                print(f"Host: {host_variant.name} (auto-selected thematic host)")
            else:
                print("Host: none (no character tagged with a fitting thematic_role yet — pure subject footage)")

        print(f"Generating script for subject: {args.subject!r} ({category}, tone={args.tone})...")
        result = generate_world_script(
            region_code=region_code or "", region_label=args.region_label,
            subject_text=args.subject, subject_category=category,
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
            subject_category=category,
            culture_id=culture_row.id if args.culture_name and culture else None,
            era_label=args.era_label,
            era_year=args.era_year,
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
            subject_category=category,
            era_label=args.era_label,
            era_year=args.era_year,
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
