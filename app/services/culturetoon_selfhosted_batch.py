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

Inference runs against a RunPod Serverless endpoint (see
app/media/runpod_serverless_client.py), not a manually-managed pod — there
is no pod start/stop lifecycle for this module to own; Serverless scales
itself to zero when idle, which is the whole reason the Network-Volume
architecture (see the plan this was revised from) replaced the earlier
single-persistent-pod design. The wall-clock time budget below still
applies (a real batch window, not unbounded), it just isn't tied to any
GPU lifecycle of this module's own anymore.

**Allocation-failure handling (first job of the window only):** the
Network Volume's inference region has shown only "medium" RTX 4090
availability on RunPod, not "high," so a cold Serverless endpoint
occasionally failing to allocate a worker on the very first request of a
window is a real, expected failure mode — not hypothetical. The FIRST
Serverless job of a run goes through
generate_toon_video_selfhosted(..., use_allocation_retry=True), which
retries with backoff (RUNPOD_ALLOCATION_MAX_RETRIES/
RUNPOD_ALLOCATION_BACKOFF_SECONDS) specifically around that allocation
step. If it still fails after retrying, that's treated as symptomatic of
the whole endpoint being unavailable this run — rather than repeatedly
failing every remaining script identically, the rest of the window is
skipped, an alert email is sent (OPS_ALERT_EMAIL), and the failure is
logged with enough context (brand, endpoint, timestamp, error) to act on
without digging through logs. Every job AFTER the first one uses the plain
(non-retrying) call and relies on the existing per-script try/except below
— once a worker is warm, an individual clip failing is an ordinary,
isolated failure, not a sign the whole endpoint is down.
"""
import logging
import os
import time
import uuid as _uuid
from datetime import datetime

logger = logging.getLogger("culturix.services.culturetoon_selfhosted_batch")


class _AllocationAbort(Exception):
    """Internal signal only — raised out of _process_brand when the
    window's first Serverless job fails to allocate even after retrying,
    caught in _process_pilot_brands to stop processing the rest of the
    window and send the ops alert. Never escapes run_selfhosted_video_batch."""
    def __init__(self, brand, original_exception):
        self.brand = brand
        self.original_exception = original_exception
        super().__init__(str(original_exception))


def _send_allocation_failure_alert(brand, endpoint_id: str, exc: Exception) -> None:
    """Best-effort email alert so a dead/out-of-capacity Serverless
    endpoint is visible without digging through logs — same Resend
    call pattern as app/pipeline/nodes/digest_writer.py::_send_email.
    Fails open (logs, doesn't raise) since a notification failure must
    never mask the underlying allocation failure it's trying to surface."""
    to = os.getenv("OPS_ALERT_EMAIL", "")
    resend_key = os.getenv("RESEND_API_KEY", "")
    if not to or not resend_key:
        logger.warning("OPS_ALERT_EMAIL/RESEND_API_KEY not set — skipping allocation-failure alert email")
        return
    try:
        import resend
        resend.api_key = resend_key
        resend.Emails.send({
            "from": "alerts@culturixcloud.com",
            "to": to,
            "subject": f"Culturix: self-hosted video batch could not allocate a worker ({brand.name})",
            "html": (
                f"<p>The self-hosted video batch for brand <b>{brand.name}</b> "
                f"(id {brand.id}) could not allocate a RunPod Serverless worker on "
                f"endpoint <code>{endpoint_id}</code> after retrying.</p>"
                f"<p>Time: {datetime.utcnow().isoformat()}Z</p>"
                f"<p>Error: {exc}</p>"
                f"<p>The rest of this scheduled window was skipped rather than "
                f"repeatedly failing against the same unavailable endpoint.</p>"
            ),
        })
        logger.info("Allocation-failure alert emailed to %s", to)
    except Exception:
        logger.exception("Failed to send allocation-failure alert email to %s", to)


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


def _process_brand(session, brand, endpoint_id: str, deadline: float, job_tracker: dict) -> int:
    from app.models.toon import Toon
    from app.media import storage
    from app.media.runpod_serverless_client import RunPodServerlessError
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

        # Only the very first Serverless call of the whole window gets the
        # allocation-retry treatment — see this module's own docstring.
        is_first_job = not job_tracker["attempted"]
        job_tracker["attempted"] = True

        try:
            video_bytes = generate_toon_video_selfhosted(
                script, variants, endpoint_id, duration_seconds=duration,
                use_allocation_retry=is_first_job,
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
        except (RunPodServerlessError, TimeoutError) as exc:
            session.rollback()
            toon.status = "failed"
            toon.generation_error = str(exc)[:2000]
            if is_first_job:
                # `finally` below still runs (records usage, commits the
                # failed toon) before this propagates up to
                # _process_pilot_brands, which stops the rest of the
                # window and sends the ops alert — see this module's
                # docstring on why the first job's allocation failure is
                # treated differently from an ordinary per-clip failure.
                raise _AllocationAbort(brand, exc) from exc
            logger.warning("Self-hosted generation failed for toon %s: %s", toon.id, exc)
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


def _process_pilot_brands(pilot_brand_ids: list, endpoint_id: str, deadline: float) -> int:
    from app.db import SessionLocal
    from app.models.character_brand import CharacterBrand

    job_tracker = {"attempted": False}
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
            try:
                generated += _process_brand(session, brand, endpoint_id, deadline, job_tracker)
            except _AllocationAbort as abort:
                logger.error(
                    "Self-hosted video batch aborted — endpoint %s failed to allocate a worker for brand %s "
                    "(%s) even after retrying: %s",
                    endpoint_id, abort.brand.name, abort.brand.id, abort.original_exception,
                )
                _send_allocation_failure_alert(abort.brand, endpoint_id, abort.original_exception)
                break
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

        endpoint_id = os.getenv("RUNPOD_SERVERLESS_ENDPOINT_ID", "")
        if not endpoint_id:
            logger.warning("RUNPOD_SERVERLESS_ENDPOINT_ID is not set — nothing to do")
            return

        max_minutes = float(os.getenv("SELFHOSTED_BATCH_MAX_MINUTES", "60"))
        deadline = time.time() + max_minutes * 60

        generated = _process_pilot_brands(pilot_brand_ids, endpoint_id, deadline)

        logger.info("Self-hosted video batch done: %d videos generated", generated)
    except Exception as e:
        logger.error("Self-hosted video batch failed: %s", e)
