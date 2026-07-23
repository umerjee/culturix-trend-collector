"""
Pipeline scheduler — collection runs 4× per day, full digest once per day.
Runs inside the FastAPI process; also triggerable via POST /collect/all for
external cron reliability (recommended: set up a Railway Cron Job or cron-job.org
pointing to POST /collect/all every 6 hours as a belt-and-suspenders backup).
"""
import logging
import os
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


def run_integration_health_check():
    """Daily check of the two unofficial/no-SLA integrations (edge-tts,
    Twitter's Jina/trends24.in proxy) — see app/integration_health.py.
    Results are persisted (IntegrationHealth), not just logged, so trend-
    over-time is visible via GET /admin/integration-health, not only
    whatever's in the log at the moment someone happens to look."""
    logger.info("Integration health check starting...")
    try:
        from app.integration_health import run_all_health_checks
        results = run_all_health_checks()
        logger.info("Integration health check done: %s", results)
    except Exception as e:
        logger.error("Integration health check failed: %s", e)


def run_digest_dispatch(now=None):
    """Sends each active profile's digest email once its own delivery_freq/
    delivery_time/delivery_day_of_week conditions are met, decoupled from the
    single shared 07:00 UTC content-generation run (app.pipeline.graph via
    run_daily_pipeline). Runs every 15 minutes so delivery_time is honored
    reasonably closely without a much bigger per-profile scheduling rework.
    Idempotent via GeneratedContent.delivered — once sent, a profile is
    skipped for the rest of the day.

    `now` is an optional injected datetime (UTC) for deterministic tests;
    defaults to the real current time in production."""
    logger.info("Digest dispatch starting...")
    try:
        from datetime import datetime
        from app.db import SessionLocal
        from app.models.content_profile import ContentProfile
        from app.models.generated_content import GeneratedContent
        from app.pipeline.nodes.digest_writer import _get_user_email, _render_email, _send_email

        now = now or datetime.utcnow()
        today = now.date()
        current_hhmm = now.strftime("%H:%M")

        session = SessionLocal()
        sent = 0
        try:
            profiles = session.query(ContentProfile).filter_by(is_active=True).all()
            for profile in profiles:
                if profile.delivery_freq == "weekly" and now.weekday() != profile.delivery_day_of_week:
                    continue
                if current_hhmm < (profile.delivery_time or "07:00"):
                    continue

                content = (
                    session.query(GeneratedContent)
                    .filter_by(content_profile_id=profile.id, trend_date=today)
                    .order_by(GeneratedContent.generated_at.desc().nullslast())
                    .first()
                )
                if not content or content.delivered or not content.content_ideas:
                    continue

                email = _get_user_email(str(profile.user_id))
                if not email:
                    continue
                html = _render_email(content.content_ideas, content.clusters or [])
                _send_email(email, html)
                content.delivered = True
                session.commit()
                sent += 1
        finally:
            session.close()
        logger.info("Digest dispatch done: %d emails sent", sent)
    except Exception as e:
        logger.error("Digest dispatch failed: %s", e)



# idea.get("platform") (an LLM-suggested display value, e.g. "YouTube") to
# the internal provider key app.social.service._PROVIDERS is keyed by.
# Only platforms with a real publish() implementation belong here — adding
# a platform here without one lets candidates match but then fail at
# publish_and_record's provider lookup instead of being filtered out
# cleanly up front.
_AUTO_PUBLISH_PLATFORMS = {
    "YouTube": "youtube", "TikTok": "tiktok",
    "Instagram": "instagram", "X/Twitter": "twitter",
}


def select_auto_publish_candidate(session, profile):
    """Pure selection — the exact filters run_auto_publish() actually
    publishes against (status=='live', platform in _AUTO_PUBLISH_PLATFORMS,
    medium defaults to 'video' for pre-preferred-formats ideas), extracted
    so a read-only "next up" preview can never drift from what actually
    gets published. Returns (content, idea_index, idea, platform_key) or
    None if there's nothing eligible right now."""
    from app.models.generated_content import GeneratedContent
    from app.models.content_post import ContentPost

    content = (
        session.query(GeneratedContent)
        .filter_by(content_profile_id=profile.id)
        .order_by(GeneratedContent.generated_at.desc().nullslast())
        .first()
    )
    if not content or not content.content_ideas:
        return None

    already_posted = {
        r.idea_index for r in session.query(ContentPost.idea_index)
        .filter_by(generated_content_id=content.id).all()
    }
    candidates = [
        (i, idea) for i, idea in enumerate(content.content_ideas)
        if i not in already_posted and idea.get("status") == "live"
        and idea.get("platform") in _AUTO_PUBLISH_PLATFORMS
        # medium may be absent on ideas generated before the preferred-formats
        # feature — treat that as "video" (its prior implicit default) rather
        # than excluding old data; explicit non-video mediums are excluded since
        # Kling+video-publish only makes sense for actual video content.
        and idea.get("medium", "video") == "video"
    ]
    if not candidates:
        return None
    idea_index, idea = max(candidates, key=lambda pair: pair[1].get("relevance_score") or 0)
    return content, idea_index, idea, _AUTO_PUBLISH_PLATFORMS[idea["platform"]]


def run_auto_publish():
    """DORMANT by default — only registered when ENABLE_DIRECT_PUBLISH is
    truthy (see start()). Superseded by run_stage_and_notify(), which stages
    the same candidate and notifies the user to publish it themselves rather
    than posting on their behalf via each platform's direct API. Kept intact
    (not deleted) in case direct-API publishing is revived for a platform
    later — see CLAUDE.md's rollback notes.

    Publishes one idea per 'auto' content profile, once per day. Only
    considers ideas that already passed trend_validator.py's legitimacy/
    safety gate at generation time and haven't since been downgraded by
    Content Check (status must still be 'live') — auto-publish never
    bypasses that safety gate. Generates a video first if the chosen idea
    doesn't have one yet."""
    logger.info("Auto-publish starting...")
    try:
        from app.db import SessionLocal
        from app.models.content_profile import ContentProfile
        from app.models.generated_media import GeneratedMedia
        from app.models.content_post import ContentPost
        from app.media.service import run_generation as run_media_generation
        from app.social.service import publish_and_record

        session = SessionLocal()
        try:
            profiles = session.query(ContentProfile).filter_by(publish_mode="auto", is_active=True).all()
            published = 0
            for profile in profiles:
                candidate = select_auto_publish_candidate(session, profile)
                if not candidate:
                    continue
                content, idea_index, idea, platform_key = candidate

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
                    user_id=profile.user_id, platform=platform_key, created_via="published", status="pending",
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


def run_stage_and_notify():
    """Default replacement for run_auto_publish — stages one idea per 'auto'
    content profile per day (video generated if missing, caption compiled
    and persisted) and notifies the user via push to publish it themselves,
    keeping their Personal/Creator account's trending-audio access intact.
    Shares candidate selection with the dormant run_auto_publish() via
    select_auto_publish_candidate, so both jobs stay in lockstep about which
    idea is "next up" regardless of which one is actually live.

    "Peak traffic hour" for v1 is just this fixed daily UTC slot (same one
    run_auto_publish used) — there's no per-platform/per-region peak-hour
    intelligence anywhere in this codebase; real peak-hour targeting is a
    future enhancement, not built here."""
    logger.info("Stage-and-notify starting...")
    try:
        from app.db import SessionLocal
        from app.models.content_profile import ContentProfile
        from app.models.generated_media import GeneratedMedia
        from app.models.content_post import ContentPost
        from app.media.service import run_generation as run_media_generation
        from app.social.service import stage_and_notify, compile_caption_text

        session = SessionLocal()
        try:
            profiles = session.query(ContentProfile).filter_by(publish_mode="auto", is_active=True).all()
            staged = 0
            for profile in profiles:
                candidate = select_auto_publish_candidate(session, profile)
                if not candidate:
                    continue
                content, idea_index, idea, platform_key = candidate

                media = session.query(GeneratedMedia).filter_by(
                    generated_content_id=content.id, idea_index=idea_index,
                    media_type="video", status="done",
                ).first()
                if not media:
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
                    user_id=profile.user_id, platform=platform_key,
                    created_via="staged", status="staged",
                    caption_text=compile_caption_text(idea),
                )
                session.add(post)
                session.commit()
                stage_and_notify(str(post.id))
                staged += 1
        finally:
            session.close()
        logger.info("Stage-and-notify done: %d posts staged", staged)
    except Exception as e:
        logger.error("Stage-and-notify failed: %s", e)


def _direct_publish_enabled() -> bool:
    return os.getenv("ENABLE_DIRECT_PUBLISH", "").lower() in ("1", "true", "yes")


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
    # Stage-and-notify (default) or auto-publish (dormant, ENABLE_DIRECT_PUBLISH=true
    # only) — one idea per 'auto' content profile, 11:00 UTC (after the above two).
    # Mutually exclusive on the same job id/slot, so there's never a double-publish race.
    if _direct_publish_enabled():
        scheduler.add_job(run_auto_publish, CronTrigger(hour=11, minute=0), id="auto_publish")
        publish_job_desc = "auto-publish (direct API) at 11:00 UTC"
    else:
        scheduler.add_job(run_stage_and_notify, CronTrigger(hour=11, minute=0), id="stage_and_notify")
        publish_job_desc = "stage & notify at 11:00 UTC"
    # Digest email dispatch — every 15 min, per-profile delivery_freq/delivery_time/
    # delivery_day_of_week gating (decoupled from the shared 07:00 UTC generation run)
    scheduler.add_job(run_digest_dispatch, CronTrigger(minute="*/15"), id="digest_dispatch")
    # Integration health check — once daily, 12:00 UTC (after the other morning jobs)
    scheduler.add_job(run_integration_health_check, CronTrigger(hour=12, minute=0), id="integration_health_check")
    scheduler.start()
    logger.info(
        "Scheduler started — collection at 01:00/07:00/13:00/19:00 UTC, "
        "full pipeline at 07:00 UTC, content check at 09:00 UTC, "
        "post metrics refresh at 10:00 UTC, %s, "
        "digest dispatch every 15 min, integration health check at 12:00 UTC",
        publish_job_desc,
    )


def stop():
    scheduler.shutdown(wait=False)
