"""Generates one ToonScene's video independently — the fine-grained
production unit from docs/culturix-character-studio-upgrade.md §3/Phase 5.
Mirrors app/services/culturetoon_video.py::generate_video_for_toon's shape
(load row -> set in-progress status -> do slow work -> write result back ->
catch-and-record-error -> finally: session.close()), scoped to a single
shot instead of a whole script.

Known simplification vs. generate_video_for_toon: no ElevenLabs dubbing
branch here — a scene is one short beat with at most one line of dialogue,
Kling's native audio is judged sufficient for v1. Revisit only if scenes
turn out to need per-character voice overrides in practice."""
import logging
import os
import tempfile
import uuid as _uuid

logger = logging.getLogger("culturix.services.culturetoon_scene")


def generate_scene_video(user_id, scene_id) -> None:
    from app.db import SessionLocal
    from app.models.toon_scene import ToonScene
    from app.models.character_variant import CharacterVariant
    from app.models.toon_background import ToonBackground
    from app.media.kling_omni import KlingOmniProvider, KlingOmniError
    from app.services.culturetoon_script import build_kling_prompt, ToonScriptGenerationError
    from app.services.culturetoon_usage import record_usage, estimate_video_cost
    from app.media import storage

    session = SessionLocal()
    scene = None
    try:
        scene = session.query(ToonScene).filter_by(id=_uuid.UUID(str(scene_id))).first()
        if not scene:
            return

        cast_ids = list(scene.character_variant_ids or [])
        if not cast_ids:
            raise ValueError("Scene has no cast — assign at least one character variant before generating")

        variants = session.query(CharacterVariant).filter(
            CharacterVariant.id.in_([_uuid.UUID(v) for v in cast_ids])
        ).all()
        variants_by_id = {str(v.id): v for v in variants}
        missing = [vid for vid in cast_ids if vid not in variants_by_id]
        if missing:
            raise ValueError(f"Character variant(s) not found: {missing}")
        not_ready = [v.name for v in variants if v.element_status != "ready"]
        if not_ready:
            raise ValueError(f"Character(s) not registered as a ready Kling element: {', '.join(not_ready)}")

        scene.status = "generating"
        scene.generation_error = None
        scene.generation_attempts = (scene.generation_attempts or 0) + 1
        session.commit()

        shot = {
            "shot_number": 1,
            "duration_seconds": scene.duration_seconds,
            "action": scene.action or "",
            "expression": scene.expression,
            "dialogue": scene.dialogue,
        }
        if len(cast_ids) > 1:
            shot["speaker_variant_id"] = cast_ids[0]
        element_names = (
            variants[0].kling_element_name if len(variants) == 1
            else {str(v.id): v.kling_element_name for v in variants}
        )
        prompt_text = build_kling_prompt([shot], element_names)
        contents = [{"type": "prompt", "text": prompt_text}]
        for i, v in enumerate(variants, start=1):
            contents.append({"type": "element", "element_id": v.kling_element_id, "id": f"char_{i}"})
        if scene.background_id:
            background = session.query(ToonBackground).filter_by(id=scene.background_id).first()
            if background and background.image_url:
                contents.append({"type": "refer_image", "url": background.image_url, "id": "bg_1"})

        settings = {
            "multi_shot": False,
            "audio": "native",
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "duration": scene.duration_seconds,
        }

        result = KlingOmniProvider().generate_omni_video(contents, settings)
        scene.kling_task_id = result["task_id"]
        session.commit()

        with tempfile.TemporaryDirectory(prefix=f"scene-{scene_id}-") as tmp_dir:
            raw_path = os.path.join(tmp_dir, "raw.mp4")
            with open(raw_path, "wb") as f:
                f.write(result["video_bytes"])
            with open(raw_path, "rb") as f:
                url = storage.upload(
                    f.read(),
                    f"culturetoons/{scene.brand_id}/episodes/{scene.episode_id}/scenes/{scene.id}/raw-{_uuid.uuid4().hex[:8]}.mp4",
                    "video/mp4",
                )

        video_duration = result.get("duration_seconds") or scene.duration_seconds
        record_usage(
            session, user_id=user_id, brand_id=scene.brand_id, episode_id=scene.episode_id, scene_id=scene.id,
            provider="kling_omni", generation_type="scene_video",
            output_units=int(video_duration), cost_usd=estimate_video_cost(video_duration),
        )

        # Same regeneration-history reasoning as Toon.previous_video_urls —
        # regenerating a scene must not silently discard a previous take.
        if scene.video_url:
            scene.previous_video_urls = (scene.previous_video_urls or []) + [scene.video_url]
        scene.video_url = url
        scene.status = "ready"
        session.commit()
        logger.info("Scene %s generated for episode %s", scene_id, scene.episode_id)

    except (ValueError, KlingOmniError, ToonScriptGenerationError) as exc:
        session.rollback()
        if scene:
            scene.status = "failed"
            scene.generation_error = str(exc)[:2000]
            session.commit()
        logger.error("Scene generation failed for %s: %s", scene_id, exc)
    except Exception as exc:
        session.rollback()
        if scene:
            scene.status = "failed"
            scene.generation_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Scene generation failed unexpectedly for %s", scene_id)
    finally:
        session.close()


def assemble_scene_from_shots(user_id, scene_id) -> None:
    """The Shot-based analogue of app/services/culturetoon_episode.py's
    assemble_episode_from_scenes — concatenates every "ready" ToonShot's
    generated_asset_id (shot_number order) into the scene's own video_url,
    instead of the scene generating as one direct Kling call
    (generate_scene_video above, unchanged, still the right choice for a
    scene simple enough not to need multiple shots). A shot left in
    "idea"/"generating"/"failed" is skipped, not a hard blocker — same
    reasoning as episode assembly: regenerating one failed shot and
    re-assembling is the whole point of shots being independently
    regeneratable."""
    from app.db import SessionLocal
    from app.models.toon_scene import ToonScene
    from app.models.toon_shot import ToonShot
    from app.services.culturetoon_episode import _stitch_video_urls, StitchError
    import httpx as _httpx

    session = SessionLocal()
    scene = None
    try:
        scene = session.query(ToonScene).filter_by(id=_uuid.UUID(str(scene_id))).first()
        if not scene:
            return

        shots = (
            session.query(ToonShot)
            .filter_by(scene_id=scene.id, generation_status="ready")
            .order_by(ToonShot.shot_number.asc())
            .all()
        )
        if len(shots) < 1:
            raise ValueError("No ready shots to assemble — generate at least one shot's video first")

        scene.status = "generating"
        scene.generation_error = None
        session.commit()

        scene.video_url = _stitch_video_urls(
            [s.generated_asset_id for s in shots],
            f"culturetoons/{scene.brand_id}/episodes/{scene.episode_id}/scenes/{scene.id}/final.mp4",
            tmp_prefix=f"scene-{scene.id}-",
        )
        scene.status = "ready"
        session.commit()
        logger.info("Assembled scene %s from %d shots", scene_id, len(shots))

    except (ValueError, StitchError, _httpx.HTTPError) as exc:
        session.rollback()
        if scene:
            scene.status = "failed"
            scene.generation_error = str(exc)[:2000]
            session.commit()
        logger.error("Scene shot assembly failed for %s: %s", scene_id, exc)
    except Exception as exc:
        session.rollback()
        if scene:
            scene.status = "failed"
            scene.generation_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Scene shot assembly failed unexpectedly for %s", scene_id)
    finally:
        session.close()
