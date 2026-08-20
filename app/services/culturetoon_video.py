"""Orchestrates one Toon's video generation end to end: builds the Kling
Omni multi-shot prompt from its shot-structured ToonScript, generates the
video (character-consistent via the variant's registered Kling Element),
optionally dubs in ElevenLabs dialogue audio, and uploads the result as the
one persistent video (raw_video_url, auto-promoted to final_video_url —
no candidate-clip picking step). Mirrors
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

# Kling Omni's actual per-call cap on distinct character elements is NOT
# confirmed anywhere in this codebase or a live call — the only source is
# an earlier planning doc built from pasted docs, the same kind of
# unverified assumption that turned out wrong for the auth mechanism
# earlier in this product's build (corrected only after a live dashboard
# screenshot). Capped defensively at 3 here so a script with more distinct
# speakers than Kling can actually accept fails with a clear error instead
# of an unpredictable API response — re-verify against Kling's real
# docs/dashboard and adjust this constant if it turns out to be wrong.
MAX_CHARACTERS_PER_VIDEO = 3


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
        # Deliberately NOT -shortest — confirmed live: dialogue audio is
        # placed sequentially, not time-aligned to Kling's actual output
        # duration (see this function's own docstring), so the audio
        # track is very often shorter than the video. -shortest truncates
        # the OUTPUT to the shorter stream, which was silently cutting off
        # the tail of the video (everything after the last line of
        # dialogue finishes) instead of just letting it play out silent.
        ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
         "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", dubbed_path],
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
    from app.media import storage
    from app.social.crypto import decrypt

    session = SessionLocal()
    toon = None
    try:
        toon = session.query(Toon).filter_by(id=_uuid.UUID(str(toon_id))).first()
        if not toon:
            return

        script = session.query(ToonScript).filter_by(id=toon.script_id).first()
        if not script:
            raise ValueError("Toon's script is missing")
        if not script.shots:
            raise ValueError("Script has no shot data — regenerate it via the shot-structured generator")

        # Full cast for this script: character_variant_ids when set (a
        # multi-character script), else fall back to the script's own
        # primary variant, else the toon's own variant (scripts predating
        # multi-character support always have character_variant_id set, so
        # this last fallback is just extra safety, not the common path).
        # Normalized to strings throughout — character_variant_ids is
        # stored as TEXT[] (see ToonScript's docstring for why), so mixing
        # in a raw UUID object from the fallback branches would make
        # otherwise-identical ids compare unequal as dict keys below.
        cast_ids = [str(v) for v in (script.character_variant_ids or [])]
        if not cast_ids and script.character_variant_id:
            cast_ids = [str(script.character_variant_id)]
        if not cast_ids:
            cast_ids = [str(toon.character_variant_id)]
        if len(cast_ids) > MAX_CHARACTERS_PER_VIDEO:
            raise ValueError(
                f"Script has {len(cast_ids)} distinct characters, but Kling supports at most "
                f"{MAX_CHARACTERS_PER_VIDEO} per video"
            )

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

        # Primary variant drives voice_provider for the whole video — mixed
        # per-character voice sourcing (e.g. one character on Kling native,
        # another on ElevenLabs, within the same video) isn't supported;
        # known simplification, same spirit as _dub_dialogue's own
        # sequential-not-time-aligned simplification below.
        primary_variant = variants_by_id.get(str(cast_ids[0]), variants[0])

        toon.status = "animating"
        toon.generation_error = None
        toon.video_provider = "kling_omni"
        session.commit()

        element_names = {str(v.id): v.kling_element_name for v in variants}
        prompt_text = build_kling_prompt(script.shots, element_names)
        contents = [{"type": "prompt", "text": prompt_text}]
        for i, v in enumerate(variants, start=1):
            contents.append({"type": "element", "element_id": v.kling_element_id, "id": f"char_{i}"})
        if toon.background_id:
            background = session.query(ToonBackground).filter_by(id=toon.background_id).first()
            if background and background.image_url:
                contents.append({"type": "refer_image", "url": background.image_url, "id": "bg_1"})

        use_elevenlabs = primary_variant.voice_provider == "elevenlabs"
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

        from app.services.culturetoon_usage import record_usage, estimate_video_cost, estimate_voice_cost
        video_duration = result.get("duration_seconds") or total_duration
        record_usage(
            session, user_id=user_id, brand_id=toon.brand_id, toon_id=toon.id,
            provider="kling_omni", generation_type="video",
            output_units=int(video_duration), cost_usd=estimate_video_cost(video_duration),
        )

        with tempfile.TemporaryDirectory(prefix=f"toon-{toon_id}-") as tmp_dir:
            raw_path = os.path.join(tmp_dir, "raw.mp4")
            with open(raw_path, "wb") as f:
                f.write(result["video_bytes"])

            final_path = raw_path
            if use_elevenlabs:
                final_path = _dub_dialogue(tmp_dir, raw_path, script.shots, elevenlabs_key, primary_variant.elevenlabs_voice_id)
                dialogue_chars = sum(len((s.get("dialogue") or "")) for s in script.shots)
                if dialogue_chars:
                    record_usage(
                        session, user_id=user_id, brand_id=toon.brand_id, toon_id=toon.id,
                        provider="elevenlabs", generation_type="voice_dubbing",
                        input_units=dialogue_chars, cost_usd=estimate_voice_cost(dialogue_chars),
                    )

            with open(final_path, "rb") as f:
                # Unique suffix per generation, not a fixed "raw.mp4" path —
                # storage.upload upserts on conflict, so a fixed path would
                # let a regeneration silently overwrite the previous take's
                # own file underneath it, making previous_video_urls below
                # point at content that no longer exists.
                raw_url = storage.upload(
                    f.read(), f"culturetoons/{toon.brand_id}/toons/{toon.id}/raw-{_uuid.uuid4().hex[:8]}.mp4", "video/mp4"
                )
            # Regenerating used to silently discard whatever was there
            # before — confirmed live: a user regenerated to fix one issue
            # and lost an otherwise-good previous take with no way back.
            # Archive it (not raw_video_url specifically — final_video_url,
            # since that's what the user was actually looking at, which can
            # differ from raw_video_url on toons predating this behavior).
            previous_url = toon.final_video_url or toon.raw_video_url
            if previous_url:
                toon.previous_video_urls = (toon.previous_video_urls or []) + [previous_url]
            toon.raw_video_url = raw_url
            toon.final_video_url = raw_url

            # QA — see app/services/culturetoon_qa.py. Run against the local
            # final_path (still on disk inside this tempdir) rather than
            # re-downloading raw_url. Not a gate: a QA failure still leaves
            # the toon "ready", just with publish_recommended=False for the
            # frontend to warn on — a human always makes the final call.
            from app.services.culturetoon_qa import run_full_qa
            culture_ids = list({v.culture_id for v in variants if v.culture_id})
            cultures_for_qa = []
            if culture_ids:
                from app.models.culture import Culture
                cultures_for_qa = [
                    {"name": c.name, "stereotypes_to_avoid": c.stereotypes_to_avoid or []}
                    for c in session.query(Culture).filter(Culture.id.in_(culture_ids)).all()
                ]
            qa_results = run_full_qa(
                final_path, total_duration, script.hook_line, script.tone or "funny",
                script.shots, cultures_for_qa,
            )
            toon.qa_results = qa_results
            toon.publish_recommended = qa_results["publish_recommended"]
            session.commit()

        toon.status = "ready"
        session.commit()
        logger.info("Video generation complete for toon %s", toon_id)

    except (ValueError, KlingOmniError, ElevenLabsError, ToonScriptGenerationError) as exc:
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
