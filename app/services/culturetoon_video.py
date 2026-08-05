"""Orchestrates one Toon's video generation end to end: builds the Kling
Omni multi-shot prompt from its shot-structured ToonScript, generates the
video (character-consistent via the variant's registered Kling Element),
optionally dubs in ElevenLabs dialogue audio, uploads the raw video, and
cuts 3-4 candidate clips from it. Mirrors
app/shopify/reels.py::generate_reel_for_product's shape exactly (load row ->
set in-progress status -> do slow work -> write result back ->
catch-and-record-error -> finally: session.close()).
"""
import logging
import os
import subprocess
import tempfile
import uuid as _uuid

logger = logging.getLogger("culturix.services.culturetoon_video")


def _dub_dialogue(tmp_dir: str, video_path: str, shots: list, api_key: str, voice_id: str) -> str:
    """Synthesizes each shot's dialogue via ElevenLabs, concatenates them
    into one continuous track, and muxes it over the (silent) Kling video
    from the start. Known simplification: dialogue is placed sequentially,
    not time-aligned to each shot's exact boundary — Kling's actual
    multi-shot output timing isn't guaranteed to match the requested shot
    durations precisely anyway, so per-shot alignment would be illusory
    precision. Returns the path to the dubbed video, or the original
    (silent) video_path unchanged if the script has no dialogue anywhere."""
    from app.media.elevenlabs_voice import ElevenLabsProvider, ElevenLabsError

    if not voice_id:
        raise ElevenLabsError("voice_provider is 'elevenlabs' but the character variant has no elevenlabs_voice_id set")

    provider = ElevenLabsProvider(api_key)
    segment_paths = []
    for i, shot in enumerate(shots):
        dialogue = (shot.get("dialogue") or "").strip()
        if not dialogue:
            continue
        audio_bytes = provider.synthesize(dialogue, voice_id)
        seg_path = os.path.join(tmp_dir, f"dub_{i}.mp3")
        with open(seg_path, "wb") as f:
            f.write(audio_bytes)
        segment_paths.append(seg_path)

    if not segment_paths:
        return video_path

    list_path = os.path.join(tmp_dir, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")
    audio_path = os.path.join(tmp_dir, "dialogue.mp3")
    concat_result = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", audio_path],
        capture_output=True, text=True, timeout=60,
    )
    if concat_result.returncode != 0:
        raise ElevenLabsError(f"ffmpeg failed concatenating dialogue audio: {concat_result.stderr[-1000:]}")

    dubbed_path = os.path.join(tmp_dir, "dubbed.mp4")
    mux_result = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
         "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", "-shortest", dubbed_path],
        capture_output=True, text=True, timeout=60,
    )
    if mux_result.returncode != 0:
        raise ElevenLabsError(f"ffmpeg failed muxing dialogue audio: {mux_result.stderr[-1000:]}")

    return dubbed_path


def generate_video_for_toon(user_id, toon_id) -> None:
    from app.db import SessionLocal
    from app.models.toon import Toon
    from app.models.toon_script import ToonScript
    from app.models.character_variant import CharacterVariant
    from app.models.character_brand import CharacterBrand
    from app.models.toon_background import ToonBackground
    from app.media.kling_omni import KlingOmniProvider, KlingOmniError
    from app.media.elevenlabs_voice import ElevenLabsError
    from app.services.culturetoon_script import build_kling_prompt, ToonScriptGenerationError
    from app.services.culturetoon_clip_cutter import cut_clips, ClipCutError
    from app.media import storage
    from app.social.crypto import decrypt

    session = SessionLocal()
    toon = None
    try:
        toon = session.query(Toon).filter_by(id=_uuid.UUID(str(toon_id))).first()
        if not toon:
            return

        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        variant = session.query(CharacterVariant).filter_by(id=toon.character_variant_id).first()
        if not script or not variant:
            raise ValueError("Toon's script or character variant is missing")
        if not script.shots:
            raise ValueError("Script has no shot data — regenerate it via the shot-structured generator")
        if variant.element_status != "ready":
            raise ValueError(f"Character variant is not a ready Kling element (status={variant.element_status})")

        toon.status = "animating"
        toon.generation_error = None
        session.commit()

        prompt_text = build_kling_prompt(script.shots, variant.kling_element_name)
        contents = [
            {"type": "prompt", "text": prompt_text},
            {"type": "element", "element_id": variant.kling_element_id, "id": "char_1"},
        ]
        if toon.background_id:
            background = session.query(ToonBackground).filter_by(id=toon.background_id).first()
            if background and background.image_url:
                contents.append({"type": "refer_image", "url": background.image_url, "id": "bg_1"})

        use_elevenlabs = variant.voice_provider == "elevenlabs"
        elevenlabs_key = None
        if use_elevenlabs:
            brand = session.query(CharacterBrand).filter_by(id=toon.brand_id).first()
            if brand and brand.elevenlabs_api_key_encrypted:
                elevenlabs_key = decrypt(brand.elevenlabs_api_key_encrypted)
            else:
                # No key configured despite the opt-in flag — fail open to
                # Kling's native voice rather than blocking generation.
                use_elevenlabs = False

        total_duration = int(script.total_duration_seconds or sum(s.get("duration_seconds", 0) for s in script.shots))
        settings = {
            "multi_shot": True,
            "audio": "off" if use_elevenlabs else "native",
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "duration": total_duration,
        }

        result = KlingOmniProvider().generate_omni_video(contents, settings)
        toon.kling_task_id = result["task_id"]
        session.commit()

        with tempfile.TemporaryDirectory(prefix=f"toon-{toon_id}-") as tmp_dir:
            raw_path = os.path.join(tmp_dir, "raw.mp4")
            with open(raw_path, "wb") as f:
                f.write(result["video_bytes"])

            final_path = raw_path
            if use_elevenlabs:
                final_path = _dub_dialogue(tmp_dir, raw_path, script.shots, elevenlabs_key, variant.elevenlabs_voice_id)

            with open(final_path, "rb") as f:
                raw_url = storage.upload(f.read(), f"culturetoons/{toon.brand_id}/toons/{toon.id}/raw.mp4", "video/mp4")
            toon.raw_video_url = raw_url
            session.commit()

            clip_infos = cut_clips(final_path, tmp_dir)
            clip_urls = []
            for i, info in enumerate(clip_infos):
                with open(info["path"], "rb") as f:
                    url = storage.upload(
                        f.read(), f"culturetoons/{toon.brand_id}/toons/{toon.id}/clip_{i + 1}.mp4", "video/mp4"
                    )
                clip_urls.append(url)
            toon.clip_video_urls = clip_urls

        toon.status = "ready"
        session.commit()
        logger.info("Video generation complete for toon %s", toon_id)

    except (ValueError, KlingOmniError, ElevenLabsError, ClipCutError, ToonScriptGenerationError) as exc:
        session.rollback()
        if toon:
            toon.status = "failed"
            toon.generation_error = str(exc)[:2000]
            session.commit()
        logger.error("Video generation failed for toon %s: %s", toon_id, exc)
    except Exception as exc:
        session.rollback()
        if toon:
            toon.status = "failed"
            toon.generation_error = f"Unexpected error: {exc}"[:2000]
            session.commit()
        logger.exception("Video generation failed unexpectedly for toon %s", toon_id)
    finally:
        session.close()
