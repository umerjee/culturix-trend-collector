"""Scheduled batch runner for self-hosted (RunPod+ComfyUI+LTX-2) video
generation — the entry point app/scheduler.py registers behind
ENABLE_SELFHOSTED_VIDEO. This is Culturix's own infrastructure (not a
per-brand/per-user feature — see the plan this was built from), so which
brands it runs against is an ops decision made via the
SELFHOSTED_VIDEO_BRAND_IDS env var, not a customer-facing setting.

Composes directly with the trend-dispatch feature
(app.scheduler.run_culturetoon_trend_dispatch): a script auto-drafted from a
trend, approved by the brand owner, is exactly the kind of "ToonScript with
status=approved and no Toon yet" this batch job picks up — closing that loop
end to end without a human ever clicking "Generate video."

Pod lifecycle is managed once per whole batch window, not per-clip, since
starting/stopping per clip would waste the pod's ~1-2 min boot time on every
single job. The pod is guaranteed to stop even if a job hangs or raises
(spec's hard cost-control requirement) via the try/finally around the whole
window.
"""
import logging
import os
import time
import uuid as _uuid

logger = logging.getLogger("culturix.services.culturetoon_selfhosted_batch")


def _pilot_brand_ids() -> list:
    raw = os.getenv("SELFHOSTED_VIDEO_BRAND_IDS", "")
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(_uuid.UUID(part))
        except ValueError:
            logger.warning("Ignoring invalid UUID in SELFHOSTED_VIDEO_BRAND_IDS: %s", part)
    return ids


def find_approved_scripts_without_toon(session, brand_id) -> list:
    """ToonScript rows for this brand with status="approved" that have no
    Toon yet — same "find work" shape as select_auto_publish_candidate
    (app/scheduler.py), adapted to CultureToons' script/toon pair."""
    from app.models.toon_script import ToonScript
    from app.models.toon import Toon

    scripts = session.query(ToonScript).filter(
        ToonScript.brand_id == brand_id, ToonScript.status == "approved",
    ).all()
    return [s for s in scripts if session.query(Toon.id).filter_by(script_id=s.id).first() is None]


def _resolve_cast(session, script) -> list:
    from app.models.character_variant import CharacterVariant

    cast_ids = [str(v) for v in (script.character_variant_ids or [])]
    if not cast_ids and script.character_variant_id:
        cast_ids = [str(script.character_variant_id)]
    if not cast_ids:
        return []
    return session.query(CharacterVariant).filter(
        CharacterVariant.id.in_([_uuid.UUID(v) for v in cast_ids])
    ).all()


def _script_duration(script) -> float:
    return (
        script.total_duration_seconds
        or sum(s.get("duration_seconds", 0) for s in (script.shots or []))
        or 5
    )


def _process_brand(session, brand, comfyui_url: str, deadline: float) -> int:
    from app.models.toon import Toon
    from app.media import storage
    from app.services.culturetoon_selfhosted_video import (
        generate_toon_video_selfhosted, SelfHostedVideoGenerationError,
    )
    from app.services.culturetoon_usage import record_usage, estimate_selfhosted_video_cost

    generated = 0
    for script in find_approved_scripts_without_toon(session, brand.id):
        if time.time() > deadline:
            break

        variants = _resolve_cast(session, script)
        if not variants:
            logger.warning("Script %s has no resolvable cast — skipping", script.id)
            continue

        duration = _script_duration(script)
        toon = Toon(
            brand_id=brand.id, character_variant_id=variants[0].id, script_id=script.id,
            title=script.hook_line, status="animating", video_provider="self_hosted",
        )
        session.add(toon)
        session.commit()

        try:
            video_bytes = generate_toon_video_selfhosted(
                script, variants, comfyui_url, duration_seconds=duration,
            )
            video_url = storage.upload(
                video_bytes,
                f"culturetoons/{brand.id}/toons/{toon.id}/raw-{_uuid.uuid4().hex[:8]}.mp4",
                "video/mp4",
            )
            toon.raw_video_url = video_url
            toon.final_video_url = video_url
            toon.status = "ready"
            generated += 1
        except SelfHostedVideoGenerationError as exc:
            session.rollback()
            toon.status = "failed"
            toon.generation_error = str(exc)[:2000]
            logger.warning("Self-hosted generation skipped for toon %s: %s", toon.id, exc)
        except Exception as exc:
            session.rollback()
            toon.status = "failed"
            toon.generation_error = f"Unexpected error: {exc}"[:2000]
            logger.exception("Self-hosted generation failed unexpectedly for toon %s", toon.id)
        finally:
            # Recorded regardless of outcome — a failed generation still
            # burned GPU time. cost_usd is a PLACEHOLDER-tier estimate, same
            # honesty as culturetoon_usage.py's existing Kling Omni/
            # ElevenLabs figures.
            record_usage(
                session, user_id=brand.user_id, brand_id=brand.id, toon_id=toon.id,
                provider="runpod_ltx", generation_type="toon_video_selfhosted",
                output_units=int(duration), cost_usd=estimate_selfhosted_video_cost(duration),
            )
            session.commit()

    return generated


def _process_pilot_brands(pilot_brand_ids: list, comfyui_url: str, deadline: float) -> int:
    from app.db import SessionLocal
    from app.models.character_brand import CharacterBrand

    session = SessionLocal()
    try:
        brands = session.query(CharacterBrand).filter(
            CharacterBrand.id.in_(pilot_brand_ids), CharacterBrand.is_active.is_(True),
        ).all()
        generated = 0
        for brand in brands:
            if time.time() > deadline:
                logger.warning("Self-hosted video batch hit its time budget — stopping early")
                break
            generated += _process_brand(session, brand, comfyui_url, deadline)
        return generated
    finally:
        session.close()


def run_selfhosted_video_batch() -> None:
    """The scheduled entry point (app.scheduler, gated behind
    ENABLE_SELFHOSTED_VIDEO). Fails safe: an empty/unset
    SELFHOSTED_VIDEO_BRAND_IDS processes nothing rather than defaulting to
    every CultureToons brand."""
    logger.info("Self-hosted video batch starting...")
    try:
        pilot_brand_ids = _pilot_brand_ids()
        if not pilot_brand_ids:
            logger.info("SELFHOSTED_VIDEO_BRAND_IDS is empty — nothing to do")
            return

        pod_id = os.getenv("RUNPOD_POD_ID", "")
        max_minutes = float(os.getenv("SELFHOSTED_BATCH_MAX_MINUTES", "60"))
        deadline = time.time() + max_minutes * 60
        generated = 0

        from app.media import runpod_client
        try:
            runpod_client.start_pod(pod_id)
            comfyui_url = runpod_client.wait_for_pod_ready(pod_id)
            generated = _process_pilot_brands(pilot_brand_ids, comfyui_url, deadline)
        finally:
            # Guaranteed to fire on any exception or early time-budget
            # break above — a hung job can never leave the pod (and its
            # billing) running. See runpod_client.stop_pod's own
            # swallow-and-log behavior for why this can't itself raise.
            if pod_id:
                runpod_client.stop_pod(pod_id)

        logger.info("Self-hosted video batch done: %d videos generated", generated)
    except Exception as e:
        logger.error("Self-hosted video batch failed: %s", e)
