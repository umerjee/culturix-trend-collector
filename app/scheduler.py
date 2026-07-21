"""
Pipeline scheduler — collection runs 4× per day, full digest once per day.
Runs inside the FastAPI process; also triggerable via POST /collect/all for
external cron reliability (recommended: set up a Railway Cron Job or cron-job.org
pointing to POST /collect/all every 6 hours as a belt-and-suspenders backup).
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("culturix.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")


def run_collection():
    """Collect fresh signals from all platforms. Runs 4× per day."""
    logger.info("Collection run starting...")
    try:
        from app.collectors.orchestrator import run_all_collectors
        results = run_all_collectors()
        logger.info("Collection done: %s", results)
    except Exception as e:
        logger.error("Collection failed: %s", e)


def run_daily_pipeline():
    """Full pipeline, orchestrated by LangGraph (app.pipeline.graph):
    collect → translate → embed → cluster+persist → personas → content → digests.
    Runs once per day at 07:00 UTC so digests are ready for morning use."""
    logger.info("Daily pipeline starting...")

    # Collect (also triggered independently 3 other times per day)
    run_collection()

    try:
        from app.pipeline.graph import run_pipeline
        result = run_pipeline()
        logger.info(
            "Daily pipeline complete. Clusters: %d, users processed: %d, errors: %s",
            len(result.get("clusters", [])),
            len(result.get("generated_content", [])),
            result.get("errors", []),
        )
    except Exception as e:
        logger.error("Daily pipeline failed: %s", e)


def run_content_check():
    """Daily audit of previously generated content ideas — flags stale ones.
    Runs once per day at 09:00 UTC, after the content engine has run."""
    logger.info("Content Check starting...")
    try:
        from app.pipeline.nodes.content_check import run_content_check as _run_check
        result = _run_check()
        logger.info("Content Check done: %s", result)
    except Exception as e:
        logger.error("Content Check failed: %s", e)


def run_post_metrics_refresh():
    """Re-fetch engagement metrics for posts still inside their tracking
    window (posted_at + 14 days). Runs once per day, after Content Check."""
    logger.info("Post metrics refresh starting...")
    try:
        from datetime import datetime
        from app.db import SessionLocal
        from app.models.content_post import ContentPost
        from app.social.service import fetch_and_record

        session = SessionLocal()
        try:
            rows = (
                session.query(ContentPost)
                .filter(ContentPost.tracking_until.isnot(None))
                .filter(ContentPost.tracking_until >= datetime.utcnow())
                .filter(ContentPost.status.in_(["tracked", "pending"]))
                .all()
            )
            post_ids = [str(r.id) for r in rows]
        finally:
            session.close()

        for post_id in post_ids:
            fetch_and_record(post_id)
        logger.info("Post metrics refresh done: %d posts", len(post_ids))
    except Exception as e:
        logger.error("Post metrics refresh failed: %s", e)


def run_auto_publish():
    """Publishes one idea per 'auto' content profile, once per day. Only
    considers ideas that already passed trend_validator.py's legitimacy/
    safety gate at generation time and haven't since been downgraded by
    Content Check (status must still be 'live') — auto-publish never
    bypasses that safety gate. Generates a video first if the chosen idea
    doesn't have one yet."""
    logger.info("Auto-publish starting...")
    try:
        from app.db import SessionLocal
        from app.models.content_profile import ContentProfile
        from app.models.generated_content import GeneratedContent
        from app.models.generated_media import GeneratedMedia
        from app.models.content_post import ContentPost
        from app.media.service import run_generation as run_media_generation
        from app.social.service import publish_and_record

        session = SessionLocal()
        try:
            profiles = session.query(ContentProfile).filter_by(publish_mode="auto", is_active=True).all()
            published = 0
            for profile in profiles:
                content = (
                    session.query(GeneratedContent)
                    .filter_by(content_profile_id=profile.id)
                    .order_by(GeneratedContent.generated_at.desc().nullslast())
                    .first()
                )
                if not content or not content.content_ideas:
                    continue

                already_posted = {
                    r.idea_index for r in session.query(ContentPost.idea_index)
                    .filter_by(generated_content_id=content.id).all()
                }
                candidates = [
                    (i, idea) for i, idea in enumerate(content.content_ideas)
                    if i not in already_posted and idea.get("status") == "live"
                    and idea.get("platform") == "YouTube"  # only platform with a publish() implementation today
                ]
                if not candidates:
                    continue
                idea_index, idea = max(candidates, key=lambda pair: pair[1].get("relevance_score") or 0)

                media = session.query(GeneratedMedia).filter_by(
                    generated_content_id=content.id, idea_index=idea_index,
                    media_type="video", status="done",
                ).first()
                if not media:
                    # Generate synchronously here (this job already runs in a
                    # background scheduler thread, not a request handler) so
                    # the publish step right after has something to publish.
                    media = GeneratedMedia(
                        generated_content_id=content.id, idea_index=idea_index,
                        media_type="video", provider="kling",
                        status="pending", prompt=idea.get("video_prompt") or idea.get("hook"),
                    )
                    session.add(media)
                    session.commit()
                    run_media_generation(
                        row_id=str(media.id), media_type="video",
                        prompt=idea.get("video_prompt") or idea.get("hook"),
                        user_id=str(profile.user_id), content_id=str(content.id), idea_index=idea_index,
                    )
                    session.refresh(media)
                    if media.status != "done":
                        continue  # generation failed — try this profile again tomorrow

                post = ContentPost(
                    generated_content_id=content.id, idea_index=idea_index,
                    user_id=profile.user_id, platform="youtube", created_via="published", status="pending",
                )
                session.add(post)
                session.commit()
                publish_and_record(str(post.id))
                published += 1
        finally:
            session.close()
        logger.info("Auto-publish done: %d posts published", published)
    except Exception as e:
        logger.error("Auto-publish failed: %s", e)


def start():
    # Collect 4× per day: 01:00, 07:00, 13:00, 19:00 UTC
    for hour in (1, 13, 19):
        scheduler.add_job(
            run_collection,
            CronTrigger(hour=hour, minute=0),
            id=f"collect_{hour:02d}h",
        )
    # Full digest pipeline once per day at 07:00 UTC (morning run includes collection)
    scheduler.add_job(run_daily_pipeline, CronTrigger(hour=7, minute=0), id="daily_pipeline")
    # Content Check — audit prior content for staleness once per day at 09:00 UTC
    scheduler.add_job(run_content_check, CronTrigger(hour=9, minute=0), id="content_check")
    # Post metrics refresh — re-fetch engagement for tracked/published posts, 10:00 UTC
    scheduler.add_job(run_post_metrics_refresh, CronTrigger(hour=10, minute=0), id="post_metrics_refresh")
    # Auto-publish — one idea per 'auto' content profile, 11:00 UTC (after the above two)
    scheduler.add_job(run_auto_publish, CronTrigger(hour=11, minute=0), id="auto_publish")
    scheduler.start()
    logger.info(
        "Scheduler started — collection at 01:00/07:00/13:00/19:00 UTC, "
        "full pipeline at 07:00 UTC, content check at 09:00 UTC, "
        "post metrics refresh at 10:00 UTC, auto-publish at 11:00 UTC"
    )


def stop():
    scheduler.shutdown(wait=False)
