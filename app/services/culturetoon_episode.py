"""Stitches a ToonEpisode's ordered parts (each an ordinary Toon, generated
via the existing unchanged app/services/culturetoon_video.py pipeline) into
one longer continuous video. Kling Omni caps a single generation call at a
short duration (the codebase's own constants assume ~15s —
app/services/culturetoon_script.py's MAX_TOTAL_SECONDS, app/media/
kling_omni.py's _OMNI_MAX_POLLS comment — both unverified against a live
call, and outside research suggests it may be as low as 10s), so a
multi-minute story is assembled here from several separately generated
parts rather than produced in one call.

Mirrors app/services/culturetoon_video.py::generate_video_for_toon's shape
(load row -> set in-progress status -> do slow work -> write result back ->
catch-and-record-error -> finally: session.close())."""
import logging
import os
import subprocess
import tempfile
import uuid as _uuid

import httpx

logger = logging.getLogger("culturix.services.culturetoon_episode")

# Generous vs. culturetoon_clip_cutter.py's 120s / _dub_dialogue's 60s — a
# 60-180s multi-part re-encode is materially heavier than either, and roughly
# matches kling_omni.py's own ~10min budget for a single Kling call.
_STITCH_TIMEOUT_SECONDS = 600


class StitchError(Exception):
    pass


def _stitch_video_urls(video_urls: list, output_path: str, tmp_prefix: str = "stitch-") -> str:
    """Shared by stitch_episode/assemble_episode_from_scenes (ToonEpisode)
    and app/services/culturetoon_scene.py::assemble_scene_from_shots
    (ToonScene) — downloads each URL, ffmpeg-concatenates them in the
    given order, uploads to output_path, and returns its URL. Callers own
    the session/status transitions and the storage path (so a scene's
    assembled video doesn't end up mislabeled under an "episodes/" path);
    this is pure ffmpeg-plumbing with no DB access of its own."""
    from app.media import storage

    with tempfile.TemporaryDirectory(prefix=tmp_prefix) as tmp_dir:
        segment_paths = []
        for i, url in enumerate(video_urls):
            resp = httpx.get(url, timeout=120)
            resp.raise_for_status()
            raw_path = os.path.join(tmp_dir, f"part_{i}_raw.mp4")
            with open(raw_path, "wb") as f:
                f.write(resp.content)

            # Normalize resolution/fps per-segment before handing off to the
            # concat demuxer below — segments can now come from two
            # different providers with different canvases (Kling Omni's
            # hardcoded 1080p vs. self-hosted LTX-2's 720x1280, both 9:16
            # but not the same absolute size), which the concat demuxer
            # itself doesn't reconcile. Scale+pad to a common canvas rather
            # than switching to -filter_complex concat, which would need to
            # handle a segment having no audio stream at all — a real
            # possibility for self-hosted output — inside the filter graph;
            # this keeps that complexity out and leaves the existing
            # concat-demuxer + re-encode below doing the actual joining,
            # unchanged.
            norm_path = os.path.join(tmp_dir, f"part_{i}.mp4")
            norm_result = subprocess.run(
                ["ffmpeg", "-y", "-i", raw_path,
                 "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30",
                 "-c:a", "copy", norm_path],
                capture_output=True, text=True, timeout=120,
            )
            if norm_result.returncode != 0:
                raise StitchError(f"ffmpeg failed normalizing video segment {i}: {norm_result.stderr[-1000:]}")
            segment_paths.append(norm_path)

        list_path = os.path.join(tmp_dir, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in segment_paths:
                f.write(f"file '{p}'\n")

        stitched_path = os.path.join(tmp_dir, "stitched.mp4")
        # Re-encode rather than -c copy: segments come from separately
        # issued generation calls with no guaranteed identical codec/
        # timebase, same category of ffmpeg gotcha
        # culturetoon_clip_cutter.py already documents for its own
        # re-encode choice. Resolution/fps mismatches are handled by the
        # per-segment normalization pass above, not here.
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", stitched_path],
            capture_output=True, text=True, timeout=_STITCH_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise StitchError(f"ffmpeg failed stitching video segments: {result.stderr[-1000:]}")

        with open(stitched_path, "rb") as f:
            return storage.upload(f.read(), output_path, "video/mp4")


def stitch_episode(user_id, episode_id) -> None:
    from app.db import SessionLocal
    from app.models.toon_episode import ToonEpisode
    from app.models.toon import Toon

    session = SessionLocal()
    episode = None
    try:
        episode = session.query(ToonEpisode).filter_by(id=_uuid.UUID(str(episode_id))).first()
        if not episode:
            return

        parts = (
            session.query(Toon)
            .filter_by(episode_id=episode.id)
            .order_by(Toon.part_order.asc())
            .all()
        )
        if len(parts) < 2:
            raise ValueError("An episode needs at least 2 parts before it can be stitched")
        missing = [str(p.part_order) for p in parts if not p.raw_video_url]
        if missing:
            raise ValueError(
                f"Part(s) at position(s) {', '.join(missing)} have no generated video yet — "
                "generate every part's video before stitching"
            )

        episode.status = "stitching"
        episode.generation_error = None
        session.commit()

        episode.final_video_url = _stitch_video_urls(
            [p.raw_video_url for p in parts],
            f"culturetoons/{episode.brand_id}/episodes/{episode.id}/final.mp4",
            tmp_prefix=f"episode-{episode.id}-",
        )
        episode.status = "ready"
        session.commit()
        logger.info("Stitched episode %s from %d parts", episode_id, len(parts))

    except (ValueError, StitchError, httpx.HTTPError) as exc:
        session.rollback()
        if episode:
            episode.status = "failed"
            episode.generation_error = str(exc)[:2000]
            session.commit()
        logger.error("Episode stitching failed for %s: %s", episode_id, exc)
    except Exception as exc:
        session.rollback()
        if episode:
            episode.status = "failed"
            episode.generation_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Episode stitching failed unexpectedly for %s", episode_id)
    finally:
        session.close()


def assemble_episode_from_scenes(user_id, episode_id) -> None:
    """The Scene-based analogue of stitch_episode — concatenates every
    "ready" ToonScene's video_url (scene_number order) into the episode's
    final_video_url, instead of chaining whole Toon "parts". A scene left
    in "idea"/"generating"/"failed" is skipped, not treated as a hard
    blocker — regenerating one failed scene and re-assembling is the whole
    point of this entity existing (see docs/culturix-character-studio-
    upgrade.md §3), so assembly should work with whatever's ready rather
    than refusing until every scene succeeds."""
    from app.db import SessionLocal
    from app.models.toon_episode import ToonEpisode
    from app.models.toon_scene import ToonScene

    session = SessionLocal()
    episode = None
    try:
        episode = session.query(ToonEpisode).filter_by(id=_uuid.UUID(str(episode_id))).first()
        if not episode:
            return

        scenes = (
            session.query(ToonScene)
            .filter_by(episode_id=episode.id, status="ready")
            .order_by(ToonScene.scene_number.asc())
            .all()
        )
        if len(scenes) < 1:
            raise ValueError("No ready scenes to assemble — generate at least one scene's video first")

        episode.status = "stitching"
        episode.generation_error = None
        session.commit()

        episode.final_video_url = _stitch_video_urls(
            [s.video_url for s in scenes],
            f"culturetoons/{episode.brand_id}/episodes/{episode.id}/final.mp4",
            tmp_prefix=f"episode-{episode.id}-",
        )
        episode.status = "ready"
        session.commit()
        logger.info("Assembled episode %s from %d scenes", episode_id, len(scenes))

    except (ValueError, StitchError, httpx.HTTPError) as exc:
        session.rollback()
        if episode:
            episode.status = "failed"
            episode.generation_error = str(exc)[:2000]
            session.commit()
        logger.error("Episode scene assembly failed for %s: %s", episode_id, exc)
    except Exception as exc:
        session.rollback()
        if episode:
            episode.status = "failed"
            episode.generation_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Episode scene assembly failed unexpectedly for %s", episode_id)
    finally:
        session.close()


def generate_episode_clips(user_id, episode_id, num_clips: int = 8, clip_seconds: int = 8) -> None:
    """Cuts highlight candidate clips from a finished episode's stitched
    video for social media. A single Toon no longer has an equivalent step
    (app/services/culturetoon_video.py promotes its one raw_video_url
    straight to final_video_url instead of cutting candidates) — this is
    now the only caller of cut_clips() (app/services/culturetoon_clip_cutter.py).
    A stitched episode is 60-180s versus a single Toon's <=15s, hence the
    larger defaults here."""
    from app.db import SessionLocal
    from app.models.toon_episode import ToonEpisode
    from app.services.culturetoon_clip_cutter import cut_clips, ClipCutError
    from app.media import storage

    session = SessionLocal()
    episode = None
    try:
        episode = session.query(ToonEpisode).filter_by(id=_uuid.UUID(str(episode_id))).first()
        if not episode:
            return
        if not episode.final_video_url:
            raise ValueError("Episode has no stitched video yet — stitch it first")

        resp = httpx.get(episode.final_video_url, timeout=120)
        resp.raise_for_status()

        with tempfile.TemporaryDirectory(prefix=f"episode-clips-{episode_id}-") as tmp_dir:
            raw_path = os.path.join(tmp_dir, "final.mp4")
            with open(raw_path, "wb") as f:
                f.write(resp.content)

            clip_infos = cut_clips(raw_path, tmp_dir, num_clips=num_clips, clip_seconds=clip_seconds)
            clip_urls = []
            for i, info in enumerate(clip_infos):
                with open(info["path"], "rb") as f:
                    url = storage.upload(
                        f.read(), f"culturetoons/{episode.brand_id}/episodes/{episode.id}/clip_{i + 1}.mp4", "video/mp4"
                    )
                clip_urls.append(url)
            episode.clip_video_urls = clip_urls

        session.commit()
        logger.info("Cut %d highlight clips for episode %s", len(clip_urls), episode_id)

    except (ValueError, ClipCutError, httpx.HTTPError) as exc:
        session.rollback()
        if episode:
            episode.generation_error = str(exc)[:2000]
            session.commit()
        logger.error("Episode clip generation failed for %s: %s", episode_id, exc)
    except Exception as exc:
        session.rollback()
        if episode:
            episode.generation_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Episode clip generation failed unexpectedly for %s", episode_id)
    finally:
        session.close()
