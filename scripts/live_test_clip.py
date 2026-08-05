"""Manual, verbose end-to-end run of the Phase 7 clip pipeline against a real
persona/cluster row and real providers (Coqui TTS, faster-whisper, ffmpeg,
Qwen/Cloudflare image, Supabase Storage). Not a pytest test — this is meant
to be run by hand once to sanity-check the live pipeline, since the first
run also downloads multi-GB model weights and can take several minutes.

Usage:
    python scripts/live_test_clip.py                  # uses the first available persona
    python scripts/live_test_clip.py --cluster         # uses the first available cluster instead
    python scripts/live_test_clip.py --source-id 42    # a specific persona id

Requires (in .env or the environment): DATABASE_URL, ANTHROPIC_API_KEY or
QWEN_API_KEY, SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY. ffmpeg/ffprobe must
be on PATH.
"""
import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("live_test_clip")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()


def _check_env():
    missing = []
    if not os.getenv("DATABASE_URL"):
        missing.append("DATABASE_URL")
    if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("QWEN_API_KEY"):
        missing.append("ANTHROPIC_API_KEY or QWEN_API_KEY")
    if not os.getenv("SUPABASE_URL"):
        missing.append("SUPABASE_URL")
    if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    import shutil
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        logger.error("ffmpeg/ffprobe not found on PATH")
        sys.exit(1)


def _ensure_clips_table():
    # Base.metadata.create_all() normally runs inside app.main's lifespan(),
    # which only fires when uvicorn actually boots the app — a standalone
    # script never triggers it, so a DB that's never had the live app start
    # since this model was added won't have the table yet.
    from app.db import Base, engine
    from app.models.clip import Clip
    Base.metadata.create_all(bind=engine, tables=[Clip.__table__])


def _find_or_create_source(use_cluster: bool, source_id):
    from app.db import SessionLocal
    from app.models.persona import Persona
    from app.models.cluster import Cluster

    session = SessionLocal()
    try:
        if use_cluster:
            model, label = Cluster, "cluster"
        else:
            model, label = Persona, "persona"

        if source_id is not None:
            row = session.query(model).filter_by(id=source_id).first()
            if not row:
                logger.error("%s %s not found", label, source_id)
                sys.exit(1)
            return label, row.id

        row = session.query(model).order_by(model.id.desc()).first()
        if row:
            logger.info("Using existing %s id=%s", label, row.id)
            return label, row.id

        if not use_cluster:
            logger.warning("No personas found in DB — creating a throwaway fixture persona for this test run.")
            fixture = Persona(
                name="Live Test Persona",
                description="A fixture persona created by scripts/live_test_clip.py for manual pipeline testing.",
                motivations="testing the clip pipeline",
                interests="short-form video, ffmpeg, TTS",
            )
            session.add(fixture)
            session.commit()
            session.refresh(fixture)
            logger.info("Created fixture persona id=%s", fixture.id)
            return "persona", fixture.id

        logger.error("No clusters found in DB and --cluster was requested — no fixture fallback for clusters.")
        sys.exit(1)
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster", action="store_true", help="Use a cluster instead of a persona")
    parser.add_argument("--source-id", type=int, default=None)
    args = parser.parse_args()

    _check_env()
    _ensure_clips_table()

    from app.routers.clips import generate_clip

    source_type, source_id = _find_or_create_source(args.cluster, args.source_id)
    logger.info("Generating clip for %s id=%s ...", source_type, source_id)
    logger.info("First run downloads XTTS (~1-2GB) and faster-whisper model weights — this can take a while.")

    start = time.time()
    try:
        result = generate_clip({"source_type": source_type, "source_id": source_id})
    except Exception as exc:
        logger.error("Clip generation raised: %s", exc)
        sys.exit(1)
    elapsed = time.time() - start

    logger.info("Done in %.1fs", elapsed)
    for k, v in result.items():
        logger.info("  %s: %s", k, v)

    if result["status"] != "complete":
        sys.exit(1)


if __name__ == "__main__":
    main()
