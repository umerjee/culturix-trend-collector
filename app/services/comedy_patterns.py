"""Cross-schema read of real, analyzed stand-up comedy structure (comedy-ai's Stage 1
pipeline, running in the `comedy_ai` schema on this same Railway Postgres instance) into
aggregate, technique-level craft guidance for CultureToons' "funny"-tone script writer.

Deliberately never surfaces a real joke's actual premise/topic/wording — only structural
numbers (which technique combinations correlate with high surprise_score, typical setup/
punchline timing). Feeding an analyzed comedian's literal joke text into a prompt that then
generates commercial content for a different, unrelated persona risks reproducing someone
else's copyrighted material verbatim — the writer prompt's own fabricated craft examples
already had to add an explicit anti-copying warning after a live case where the model
reproduced a worked example almost verbatim (2026-09-02, see culturetoon_script.py). Real
comedians' actual jokes are a strictly higher-risk version of that same failure mode, so this
module only ever returns aggregated stats across many jokes, never a single joke's content.

Fails open to [] / "" on any error (comedy_ai schema not migrated in this environment, no
rows yet, connection issue) -- the writer prompt already works without this; it's enrichment
only, never a required input."""
import logging

from sqlalchemy import text

from app.db import SessionLocal

logger = logging.getLogger("culturix.comedy_patterns")

MIN_CONFIDENCE = 0.6
MIN_SAMPLE_SIZE = 2


def get_comedy_technique_stats(limit: int = 6) -> list[dict]:
    """Aggregates real ComedyAnalysis rows into per-technique stats: how often a technique
    appears, its average surprise/complexity score, and typical timing. Returns [] on any
    failure or if there isn't enough real data yet to aggregate honestly."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT unnest(techniques) AS technique,
                   count(*) AS n,
                   avg(surprise_score) AS avg_surprise,
                   avg(complexity_score) AS avg_complexity,
                   avg(punchline_position) AS avg_punchline_position,
                   avg(tag_count) AS avg_tag_count
            FROM comedy_ai.comedy_analyses
            WHERE confidence >= :min_confidence AND techniques IS NOT NULL
            GROUP BY technique
            HAVING count(*) >= :min_sample
            ORDER BY avg(surprise_score) DESC NULLS LAST
            LIMIT :limit
        """), {"min_confidence": MIN_CONFIDENCE, "min_sample": MIN_SAMPLE_SIZE, "limit": limit}).fetchall()
        return [
            {
                "technique": r.technique,
                "sample_size": r.n,
                "avg_surprise_score": round(float(r.avg_surprise), 2) if r.avg_surprise is not None else None,
                "avg_complexity_score": round(float(r.avg_complexity), 2) if r.avg_complexity is not None else None,
                "avg_punchline_position_seconds": round(float(r.avg_punchline_position), 1) if r.avg_punchline_position is not None else None,
                "avg_tag_count": round(float(r.avg_tag_count), 1) if r.avg_tag_count is not None else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("get_comedy_technique_stats failed, returning []: %s", exc)
        return []
    finally:
        db.close()


def get_pipeline_overview() -> dict:
    """Stage 1 ingestion/analysis progress, per-comedian, for the admin dashboard --
    lets a human see whether there's enough real data yet for the stats above to be
    meaningful, not just whether the pipeline ran. Raises on failure (unlike the two
    functions above) -- the admin endpoint calling this already wraps it and returns a
    clear error, and a silent [] here would read as "zero data" instead of "query broke"."""
    db = SessionLocal()
    try:
        totals = db.execute(text("""
            SELECT
                (SELECT count(*) FROM comedy_ai.comedians) AS comedians,
                (SELECT count(*) FROM comedy_ai.videos) AS videos,
                (SELECT count(*) FROM comedy_ai.videos WHERE transcript_available) AS videos_with_transcript,
                (SELECT count(*) FROM comedy_ai.routines) AS routines,
                (SELECT count(*) FROM comedy_ai.comedy_analyses) AS jokes
        """)).fetchone()

        per_comedian = db.execute(text("""
            SELECT
                c.id, c.name,
                count(DISTINCT v.id) AS videos,
                count(DISTINCT v.id) FILTER (WHERE v.transcript_available) AS videos_with_transcript,
                count(DISTINCT r.id) AS routines,
                count(DISTINCT ca.id) AS jokes
            FROM comedy_ai.comedians c
            LEFT JOIN comedy_ai.videos v ON v.comedian_id = c.id
            LEFT JOIN comedy_ai.routines r ON r.video_id = v.id
            LEFT JOIN comedy_ai.comedy_analyses ca ON ca.video_id = v.id
            GROUP BY c.id, c.name
            ORDER BY c.name
        """)).fetchall()

        return {
            "comedians": totals.comedians,
            "videos": totals.videos,
            "videos_with_transcript": totals.videos_with_transcript,
            "routines": totals.routines,
            "jokes": totals.jokes,
            "per_comedian": [
                {
                    "id": str(r.id), "name": r.name, "videos": r.videos,
                    "videos_with_transcript": r.videos_with_transcript,
                    "routines": r.routines, "jokes": r.jokes,
                }
                for r in per_comedian
            ],
        }
    finally:
        db.close()


def get_top_structures(limit: int = 5) -> list[dict]:
    """Which joke SHAPE (the sequence of structural beats, e.g. "SETUP+MISDIRECTION+
    PUNCHLINE+TAG" -- never the actual joke text) scored highest for surprise across real
    analyzed routines. Returns [] on any failure or insufficient data."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT structure, count(*) AS n, avg(surprise_score) AS avg_surprise
            FROM comedy_ai.comedy_analyses
            WHERE confidence >= :min_confidence AND structure IS NOT NULL
            GROUP BY structure
            HAVING count(*) >= :min_sample
            ORDER BY avg(surprise_score) DESC NULLS LAST
            LIMIT :limit
        """), {"min_confidence": MIN_CONFIDENCE, "min_sample": MIN_SAMPLE_SIZE, "limit": limit}).fetchall()
        return [
            {"structure": r.structure, "sample_size": r.n,
             "avg_surprise_score": round(float(r.avg_surprise), 2) if r.avg_surprise is not None else None}
            for r in rows
        ]
    except Exception as exc:
        logger.warning("get_top_structures failed, returning []: %s", exc)
        return []
    finally:
        db.close()


def build_comedy_craft_addendum() -> str:
    """Renders the two stats queries above into a short, optional prompt block for the
    "funny"-tone writer -- real, data-backed structural guidance (timing, technique combos),
    never literal jokes. Returns "" if there isn't enough real analyzed data yet, so callers
    can skip the block entirely rather than inject an empty/misleading section."""
    technique_stats = get_comedy_technique_stats()
    structures = get_top_structures()
    if not technique_stats and not structures:
        return ""

    lines = []
    if technique_stats:
        lines.append(
            "Real technique data measured from analyzed professional stand-up (use this to "
            "choose WHICH techniques to lean on and how to pace them -- never to copy any "
            "specific joke, which this data intentionally does not include):"
        )
        for t in technique_stats:
            detail = f"- {t['technique']}: seen in {t['sample_size']} analyzed jokes"
            if t["avg_surprise_score"] is not None:
                detail += f", avg surprise {t['avg_surprise_score']}"
            if t["avg_punchline_position_seconds"] is not None:
                detail += f", punchline lands ~{t['avg_punchline_position_seconds']}s into the bit"
            if t["avg_tag_count"]:
                detail += f", avg {t['avg_tag_count']} tag(s) (a quick extra punch right after the main punchline)"
            lines.append(detail)
    if structures:
        lines.append(
            "Real joke SHAPES that scored highest for surprise in analyzed routines (the "
            "sequence of beats only -- structure your OWN beats this way, never write these "
            "labels into the script itself):"
        )
        for s in structures:
            lines.append(f"- {s['structure']} (seen {s['sample_size']}x, avg surprise {s['avg_surprise_score']})")

    return "\n".join(lines)
