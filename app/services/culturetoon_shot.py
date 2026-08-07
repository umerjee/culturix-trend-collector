"""Generates one ToonShot's video independently — the fine-grained
production unit beneath ToonScene, see docs/culturix-cinematic-shots.md:
Episode -> Scenes -> Shots -> Video Clips -> Assembly -> Final Toon.
Mirrors app/services/culturetoon_scene.py::generate_scene_video's shape
(load row -> set in-progress status -> do slow work -> write result back
-> catch-and-record-error -> finally: session.close()), but builds a
richer per-shot prompt from ToonShot's camera/lighting/composition fields
instead of just action/expression/dialogue, and always resolves character
identity + location live from the persistent Character/CharacterVariant/
ToonBackground records — a Shot never stores that data itself, only
references (character_variant_ids, background_id).

Known simplification, matching generate_scene_video's own precedent: no
ElevenLabs dubbing branch here — Kling's native audio is judged sufficient
for a single short (1-5s) shot."""
import logging
import os
import tempfile
import uuid as _uuid

logger = logging.getLogger("culturix.services.culturetoon_shot")

_MAX_SHOT_PROMPT_CHARS = 512


def build_shot_prompt(shot, element_names, location_description: str = "") -> str:
    """shot: a ToonShot ORM row. element_names: single string (one
    character) or {variant_id: element_name} dict (multi-character) — same
    contract as culturetoon_script.py::build_kling_prompt. Returns the
    single prompt string sent to Kling for this one shot (a Shot is always
    exactly one Kling call, never the multi-shot DSL build_kling_prompt
    produces for a whole script/scene)."""
    cast_ids = list(shot.character_variant_ids or [])
    if isinstance(element_names, str):
        element_refs = [f"@{element_names}"] if cast_ids and element_names else []
    else:
        element_refs = [f"@{element_names[cid]}" for cid in cast_ids if cid in element_names]

    header_parts = []
    if element_refs:
        header_parts.append(", ".join(element_refs))
    type_label = (shot.shot_type or "medium").replace("_", " ")
    header_parts.append(f"{type_label} shot")
    if shot.camera_angle:
        header_parts.append(shot.camera_angle)
    if shot.camera_movement and shot.camera_movement != "static":
        header_parts.append(f"{shot.camera_movement.replace('_', ' ')} camera movement")
    if shot.lens:
        header_parts.append(shot.lens)
    if shot.composition:
        header_parts.append(shot.composition)
    if shot.lighting:
        header_parts.append(shot.lighting)
    header = ", ".join(header_parts) + "."

    body_parts = []
    if shot.action:
        body_parts.append(shot.action)
    if shot.emotion:
        body_parts.append(f"{shot.emotion.lower()} expression")
    if shot.dialogue:
        body_parts.append(f'saying "{shot.dialogue}"')
    body = (", ".join(body_parts) + ".") if body_parts else ""

    location_part = f" Setting: {location_description}." if location_description else ""

    text = f"{header} {body}{location_part}".strip()
    if len(text) > _MAX_SHOT_PROMPT_CHARS:
        text = text[:_MAX_SHOT_PROMPT_CHARS - 1].rstrip() + "…"
    return text


def generate_shot_video(user_id, shot_id) -> None:
    from app.db import SessionLocal
    from app.models.toon_shot import ToonShot
    from app.models.toon_scene import ToonScene
    from app.models.character_variant import CharacterVariant
    from app.models.toon_background import ToonBackground
    from app.media.kling_omni import KlingOmniProvider, KlingOmniError
    from app.services.culturetoon_usage import record_usage, estimate_video_cost
    from app.media import storage

    session = SessionLocal()
    shot = None
    try:
        shot = session.query(ToonShot).filter_by(id=_uuid.UUID(str(shot_id))).first()
        if not shot:
            return
        scene = session.query(ToonScene).filter_by(id=shot.scene_id).first()

        cast_ids = list(shot.character_variant_ids or [])
        variants = []
        if cast_ids:
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

        shot.generation_status = "generating"
        shot.generation_error = None
        shot.generation_attempts = (shot.generation_attempts or 0) + 1
        session.commit()

        background_id = shot.background_id or (scene.background_id if scene else None)
        background = session.query(ToonBackground).filter_by(id=background_id).first() if background_id else None
        location_description = ((background.description or background.name) if background else "") or ""

        element_names = (
            {} if not variants
            else variants[0].kling_element_name if len(variants) == 1
            else {str(v.id): v.kling_element_name for v in variants}
        )
        prompt_text = build_shot_prompt(shot, element_names, location_description)
        shot.visual_prompt = prompt_text
        shot.motion_prompt = shot.camera_movement
        contents = [{"type": "prompt", "text": prompt_text}]
        reference_assets = []
        for i, v in enumerate(variants, start=1):
            contents.append({"type": "element", "element_id": v.kling_element_id, "id": f"char_{i}"})
            if v.image_url:
                reference_assets.append(v.image_url)
        if background and background.image_url:
            contents.append({"type": "refer_image", "url": background.image_url, "id": "bg_1"})
            reference_assets.append(background.image_url)
        shot.reference_assets = reference_assets or None

        settings = {
            "multi_shot": False, "audio": "native", "resolution": "1080p",
            "aspect_ratio": "9:16", "duration": shot.duration_seconds,
        }

        result = KlingOmniProvider().generate_omni_video(contents, settings)
        shot.kling_task_id = result["task_id"]
        shot.provider = "kling_omni"
        session.commit()

        with tempfile.TemporaryDirectory(prefix=f"shot-{shot_id}-") as tmp_dir:
            raw_path = os.path.join(tmp_dir, "raw.mp4")
            with open(raw_path, "wb") as f:
                f.write(result["video_bytes"])
            with open(raw_path, "rb") as f:
                url = storage.upload(
                    f.read(),
                    f"culturetoons/{shot.brand_id}/scenes/{shot.scene_id}/shots/{shot.id}/raw-{_uuid.uuid4().hex[:8]}.mp4",
                    "video/mp4",
                )

        video_duration = result.get("duration_seconds") or shot.duration_seconds
        record_usage(
            session, user_id=user_id, brand_id=shot.brand_id,
            episode_id=scene.episode_id if scene else None, scene_id=shot.scene_id, shot_id=shot.id,
            provider="kling_omni", generation_type="shot_video",
            output_units=int(video_duration), cost_usd=estimate_video_cost(video_duration),
        )

        # Same regeneration-history reasoning as ToonScene.previous_video_urls
        # — regenerating a shot must not silently discard a previous take.
        if shot.generated_asset_id:
            shot.previous_asset_ids = (shot.previous_asset_ids or []) + [shot.generated_asset_id]
        shot.generated_asset_id = url
        shot.generation_status = "ready"
        session.commit()
        logger.info("Shot %s generated for scene %s", shot_id, shot.scene_id)

    except (ValueError, KlingOmniError) as exc:
        session.rollback()
        if shot:
            shot.generation_status = "failed"
            shot.generation_error = str(exc)[:2000]
            session.commit()
        logger.error("Shot generation failed for %s: %s", shot_id, exc)
    except Exception as exc:
        session.rollback()
        if shot:
            shot.generation_status = "failed"
            shot.generation_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Shot generation failed unexpectedly for %s", shot_id)
    finally:
        session.close()
