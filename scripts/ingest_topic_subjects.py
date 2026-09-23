"""Populate the World subject library from specific Wikipedia topics, not a
region's whole history — for browse categories like Phenomena and Species
that bulk_ingest_world_subjects.py's per-country "History of X" sweep almost
never surfaces (that script found 1 "place" and 11 "custom" published
Features, and zero for phenomenon/species/genz, per a 2026-09-23 DB check).

Each topic gets its own Wikipedia fetch and one curated_items row (max_items=1:
a focused article is one subject, not a batch to split up, unlike a broad
"History of France" extract). subject_category is required per topic because
_CATEGORY_MAP (world_production.py) has no route to "phenomenon" or "species"
from any ingestion-pipeline category — see that module's WORLD_SUBJECT_CATEGORIES
comment for why.

Examples:
    python scripts/ingest_topic_subjects.py --dry-run
    python scripts/ingest_topic_subjects.py --category phenomenon
    python scripts/ingest_topic_subjects.py --generate   # also writes scripts (no render)
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(".env")

logger = logging.getLogger("culturix.ingest_topic_subjects")

# (Wikipedia title, subject_category). Picked for real documentation depth (a thin stub makes a
# poor source) and range within each category, not just the most obvious pick each time.
TOPICS: dict[str, list[str]] = {
    "phenomenon": [
        "Aurora",
        "Bioluminescence",
        "St. Elmo's Fire",
        "Volcanic lightning",
        "Bird migration",
        "Tsunami",
    ],
    "species": [
        "Axolotl",
        "Mimic octopus",
        "Tardigrade",
        "Komodo dragon",
        "Giant sequoia",
        "Blue whale",
    ],
    "tech": [
        "CRISPR gene editing",
        "Quantum computing",
        "Fusion power",
        "Brain–computer interface",
        "3D printing",
        "Self-driving car",
    ],
}


def ingest_topic(title: str, subject_category: str, max_items: int):
    from app.collectors.wikipedia_extracts import fetch_wikipedia_extract
    from app.db import SessionLocal
    from app.services.culturix_ingestion import ingest

    source = fetch_wikipedia_extract(title, full_text=True)
    if not source:
        logger.warning("Wikipedia source unavailable: %s", title)
        return []
    session = SessionLocal()
    try:
        rows = ingest("wikipedia", None, source["extract"], session, max_items=max_items,
                      source_ref=source["title"], source_url=source.get("url"))
    finally:
        session.close()
    return rows


def generate_for(item_id, subject_category: str, use_host: bool):
    from app.db import SessionLocal
    from app.models.curated_item import CuratedItem
    from app.services.world_production import WorldDraftExists, generate_world_draft

    session = SessionLocal()
    try:
        item = session.query(CuratedItem).filter_by(id=item_id).first()
        try:
            result = generate_world_draft(session, item, use_host=use_host, subject_category=subject_category)
            return {"ok": True, "toon_id": result.get("toon_id"), "grounded": result["grounding"].get("grounded")}
        except WorldDraftExists as exc:
            return {"ok": False, "reason": str(exc)}
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", choices=sorted(TOPICS), help="Only this category (default: all three)")
    parser.add_argument("--max-items", type=int, default=1, help="Extracted items per article (default: 1)")
    parser.add_argument("--generate", action="store_true", help="Also write a script for each newly created item")
    parser.add_argument("--use-host", action="store_true", help="Pass use_host=True when generating")
    parser.add_argument("--dry-run", action="store_true", help="Print the topic list without fetching or writing anything")
    args = parser.parse_args()

    categories = [args.category] if args.category else list(TOPICS)

    if args.dry_run:
        for category in categories:
            print(f"{category}: {', '.join(TOPICS[category])}")
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    totals = {"created": 0, "skipped_existing": 0, "failed": 0, "generated": 0, "generate_failed": 0}
    for category in categories:
        for title in TOPICS[category]:
            print(f"[{category}] {title}")
            try:
                rows = ingest_topic(title, category, max(1, args.max_items))
            except Exception:
                totals["failed"] += 1
                logger.exception("Ingestion failed: %s", title)
                continue
            if not rows:
                totals["skipped_existing"] += 1
                print("  no new item (already ingested, or nothing extractable)")
                continue
            totals["created"] += len(rows)
            for item in rows:
                print(f"  created: {item.title!r} priority={item.priority_score} decision={item.pipeline_decision}")
                # score_and_challenge's rubric (recency/popularity/cultural_weight/evergreen_value)
                # was calibrated against history/culture/place source text, not natural-phenomenon or
                # species topics — a live run scored well-documented topics like Bioluminescence and
                # Volcanic lightning as "exclude" despite good sources, because extract_items pulled a
                # narrow historical-discovery angle instead of the compelling topic itself. TOPICS
                # above is itself a hand-picked quality bar, so --generate does not defer to
                # pipeline_decision here the way an admin-triggered generate would.
                if args.generate:
                    # generate_world_draft already marks its own placeholder row "failed" on any
                    # exception (so the curator sees it), but still re-raises — a live run hit a
                    # transient "server closed the connection unexpectedly" mid-generation (a long
                    # multi-minute LLM cycle outlived the DB session) and, uncaught here, took the
                    # whole batch down with it instead of just that one topic.
                    try:
                        outcome = generate_for(item.id, category, args.use_host)
                    except Exception as exc:
                        totals["generate_failed"] += 1
                        logger.exception("Script generation failed: %s", item.title)
                        print(f"    script not written: {type(exc).__name__}: {exc}")
                        continue
                    if outcome["ok"]:
                        totals["generated"] += 1
                        print(f"    script written: toon={outcome['toon_id']} grounded={outcome['grounded']}")
                    else:
                        totals["generate_failed"] += 1
                        print(f"    script not written: {outcome['reason']}")
    print(f"Complete: {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
