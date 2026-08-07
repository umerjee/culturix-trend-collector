"""Manual, verbose live probe of the Kling Omni API (app/media/kling_omni.py)
— the ONE thing no script in this repo has done yet. Every number and
response-field-name this module's provider code relies on was transcribed
from Kling's docs, not confirmed against a real response; this script's job
is to actually make those calls, print the raw JSON at every step, and let
you (a) see whether the assumed field names/status strings are right, and
(b) manually judge things no script can verify automatically (does the
character actually speak the dialogue out loud with lip sync?).

THIS SPENDS REAL MONEY. Every test past `auth` makes a real Kling Omni
API call. Costs are unknown/unconfirmed (see app/services/culturetoon_usage.py's
own PLACEHOLDER pricing) — assume each video-generating call could cost a
few cents to a dollar depending on Kling's actual Omni pricing, and budget
accordingly. Nothing beyond `auth` runs unless you pass --yes.

Usage:
    # Free — just checks KLING_API_KEY is present and well-formed.
    python scripts/live_test_kling_omni.py --tests auth

    # The highest-priority, lowest-total-cost real check: register one
    # element from a real character reference photo, generate one short
    # clip with no dialogue (confirms connectivity + response shapes), then
    # one short clip WITH dialogue (the native-audio-lipsync question).
    python scripts/live_test_kling_omni.py --yes \
        --reference-image-url https://your-supabase-url/.../character.png

    # Everything, including the multi-character cap probe (needs 3+ image
    # URLs) and the @ElementName-repeat-per-shot comparison (2x cost).
    python scripts/live_test_kling_omni.py --yes --tests all \
        --reference-image-url https://.../kumar.png \
        --reference-image-url https://.../hans.png \
        --reference-image-url https://.../priya.png

Requires: KLING_API_KEY (Kling's newer bearer-token API key system, NOT the
older KLING_ACCESS_KEY/KLING_SECRET_KEY pair — generate one at
https://kling.ai/dev/api-key) in .env or the environment.

Test tiers (comma-separated to --tests, default "auth,element,minimal,audio"):
  auth       - free. Confirms KLING_API_KEY is set.
  element    - registers one Kling Element from --reference-image-url[0].
               Prints the raw create/poll responses in full (verifies the
               id/task_id and succeed/succeeded field-name assumptions).
  minimal    - one ~3s single-shot clip, no dialogue, using the registered
               element. Confirms the omni-video create/poll response shape
               and that a bare generation actually works end to end.
  audio      - one ~4s single-shot clip WITH dialogue + audio:"native".
               Downloads the result locally — YOU must watch/listen to it
               and judge whether the character actually speaks the line
               with lip sync. This is the single most-cited unverified
               assumption in the codebase.
  repeat     - generates a 2-shot clip twice: once with @ElementName
               repeated in every shot segment (today's default behavior),
               once with it only in shot 1. Saves both for you to compare
               character consistency. 2x cost of one clip.
  duration   - one clip at the code's assumed max total duration (15s) to
               see whether Kling accepts it, rejects it, or silently
               truncates (the "outside research suggests it may be as low
               as 10s" hedge in the code).
  multichar  - needs 3-4 --reference-image-url values. Registers the extra
               elements and generates one clip referencing all of them, to
               probe the MAX_CHARACTERS_PER_VIDEO=3 assumption.
  voice      - needs --voice-url. Registers a cloned voice, prints the raw
               response.
  all        - every tier above.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("live_test_kling_omni")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

import httpx  # noqa: E402

_BASE = "https://api-singapore.klingai.com"


def _check_env() -> str:
    api_key = os.getenv("KLING_API_KEY", "")
    if not api_key:
        logger.error(
            "KLING_API_KEY is not set. This is Kling's newer bearer-token API key "
            "system, NOT the older KLING_ACCESS_KEY/KLING_SECRET_KEY pair — that pair "
            "is already confirmed (via a real 401) not to work for this endpoint. "
            "Generate one at https://kling.ai/dev/api-key and add it to .env."
        )
        sys.exit(1)
    return api_key


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _print_json(label: str, data) -> None:
    print(f"\n--- {label} ---")
    print(json.dumps(data, indent=2, default=str)[:4000])
    print("--- end ---\n")


def _check(resp: httpx.Response, context: str) -> dict:
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(f"{context}: HTTP {resp.status_code} — {detail}")
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"{context}: {data.get('message', data)}")
    return data


def register_element(api_key: str, name: str, description: str, frontal_image_url: str) -> str:
    logger.info("Registering Kling Element %r from %s", name, frontal_image_url)
    body = {
        "element_name": name[:20],
        "element_description": description[:100],
        "reference_type": "image_refer",
        "element_image_list": {
            "frontal_image": frontal_image_url,
            "refer_images": [{"image_url": frontal_image_url}],
        },
        "tag_list": [{"tag_id": "o_102"}],
    }
    resp = httpx.post(f"{_BASE}/v1/general/advanced-custom-elements", headers=_headers(api_key), json=body, timeout=30)
    data = _check(resp, "create_element")
    _print_json("create_element response (verify: is the task id under data.task_id or data.id?)", data)
    task_id = data["data"].get("task_id") or data["data"].get("id")
    if not task_id:
        raise RuntimeError(f"Could not find a task id in create_element response: {data}")

    import time
    for i in range(24):
        time.sleep(5)
        poll = httpx.get(f"{_BASE}/v1/general/advanced-custom-elements/{task_id}", headers=_headers(api_key), timeout=20)
        pdata = _check(poll, "create_element poll")["data"]
        status = pdata.get("task_status", "")
        logger.info("  poll %d/24: task_status=%r", i + 1, status)
        if status in ("succeed", "succeeded"):
            _print_json("create_element poll response (verify: status string is 'succeed' not 'succeeded'?)", pdata)
            elements = pdata.get("task_result", {}).get("elements") or []
            if not elements:
                raise RuntimeError(f"Element task succeeded but returned no elements: {pdata}")
            element_id = str(elements[0]["element_id"])
            logger.info("Registered element_id=%s", element_id)
            return element_id
        if status == "failed":
            raise RuntimeError(f"Element registration failed: {pdata.get('task_status_msg')}")
    raise RuntimeError("Element registration did not complete within 2 minutes")


def generate_video(api_key: str, contents: list, settings: dict, out_path: Path) -> dict:
    logger.info("Generating omni video: settings=%s", settings)
    body = {"contents": contents, "settings": settings}
    resp = httpx.post(f"{_BASE}/omni-video/kling-3.0-omni", headers=_headers(api_key), json=body, timeout=30)
    data = _check(resp, "generate_omni_video")
    _print_json("generate_omni_video create response (verify: task id under data.id?)", data)
    task_id = data["data"].get("id") or data["data"].get("task_id")
    if not task_id:
        raise RuntimeError(f"Could not find a task id in generate_omni_video response: {data}")

    import time
    for i in range(60):
        time.sleep(10)
        poll = httpx.get(f"{_BASE}/tasks", headers=_headers(api_key), params={"task_ids": task_id}, timeout=20)
        pdata_list = _check(poll, "generate_omni_video poll")["data"]
        if not pdata_list:
            logger.info("  poll %d/60: no task data yet", i + 1)
            continue
        pdata = pdata_list[0]
        status = pdata.get("status", "")
        logger.info("  poll %d/60: status=%r", i + 1, status)
        if status == "succeeded":
            _print_json("generate_omni_video poll response (verify: outputs[].duration matches requested duration?)", pdata)
            outputs = pdata.get("outputs") or []
            video_output = next((o for o in outputs if o.get("type") == "video"), None)
            if not video_output or not video_output.get("url"):
                raise RuntimeError(f"Task succeeded but no video output: {pdata}")
            video_resp = httpx.get(video_output["url"], timeout=120)
            video_resp.raise_for_status()
            out_path.write_bytes(video_resp.content)
            actual_duration = video_output.get("duration")
            logger.info("Saved video to %s (requested %ss, Kling reported duration=%s)", out_path, settings.get("duration"), actual_duration)
            return {"path": str(out_path), "requested_duration": settings.get("duration"), "reported_duration": actual_duration}
        if status == "failed":
            raise RuntimeError(f"Omni video task failed: {pdata.get('message')}")
    raise RuntimeError("Omni video generation did not complete within 10 minutes")


def test_minimal(api_key: str, element_id: str, element_name: str, out_dir: Path):
    print("\n=== TEST: minimal single shot, no dialogue ===")
    contents = [
        {"type": "prompt", "text": f"shot 1, 3, @{element_name}, standing still, neutral expression.;"},
        {"type": "element", "element_id": element_id, "id": "char_1"},
    ]
    settings = {"multi_shot": False, "audio": "native", "resolution": "1080p", "aspect_ratio": "9:16", "duration": 3}
    result = generate_video(api_key, contents, settings, out_dir / "minimal.mp4")
    print(f"RESULT: {result}")


def test_audio(api_key: str, element_id: str, element_name: str, out_dir: Path):
    print("\n=== TEST: native audio + dialogue (THE key open question) ===")
    contents = [
        {"type": "prompt", "text": f'shot 1, 4, @{element_name}, smiling, happy expression, saying "Hello there, how are you today?".;'},
        {"type": "element", "element_id": element_id, "id": "char_1"},
    ]
    settings = {"multi_shot": False, "audio": "native", "resolution": "1080p", "aspect_ratio": "9:16", "duration": 4}
    result = generate_video(api_key, contents, settings, out_dir / "audio_dialogue.mp4")
    print(f"RESULT: {result}")
    print(">>> ACTION REQUIRED: open the saved file and check — does the character actually")
    print(">>> speak 'Hello there, how are you today?' out loud, with lip movement matching")
    print(">>> the words? This cannot be checked automatically.")


def test_repeat(api_key: str, element_id: str, element_name: str, out_dir: Path):
    print("\n=== TEST: @ElementName repeated every shot vs only shot 1 ===")
    repeated = f"shot 1, 2, @{element_name}, waves hello, happy expression.; shot 2, 2, @{element_name}, turns and walks away, neutral expression.;"
    once = f"shot 1, 2, @{element_name}, waves hello, happy expression.; shot 2, 2, turns and walks away, neutral expression.;"
    for label, prompt_text in (("repeated_every_shot", repeated), ("named_once", once)):
        contents = [{"type": "prompt", "text": prompt_text}, {"type": "element", "element_id": element_id, "id": "char_1"}]
        settings = {"multi_shot": True, "audio": "off", "resolution": "1080p", "aspect_ratio": "9:16", "duration": 4}
        result = generate_video(api_key, contents, settings, out_dir / f"repeat_{label}.mp4")
        print(f"RESULT ({label}): {result}")
    print(">>> ACTION REQUIRED: compare repeat_repeated_every_shot.mp4 vs repeat_named_once.mp4 —")
    print(">>> does character consistency in shot 2 actually degrade when @Name isn't repeated?")


def test_duration(api_key: str, element_id: str, element_name: str, out_dir: Path):
    print("\n=== TEST: max total duration probe (assumed 15s ceiling) ===")
    prompt = (
        f"shot 1, 3, @{element_name}, looks around, confused expression.; "
        f"shot 2, 3, @{element_name}, shrugs, neutral expression.; "
        f"shot 3, 3, @{element_name}, smiles, happy expression.; "
        f"shot 4, 3, @{element_name}, waves, happy expression.; "
        f"shot 5, 3, @{element_name}, walks away, neutral expression.;"
    )
    contents = [{"type": "prompt", "text": prompt}, {"type": "element", "element_id": element_id, "id": "char_1"}]
    settings = {"multi_shot": True, "audio": "off", "resolution": "1080p", "aspect_ratio": "9:16", "duration": 15}
    try:
        result = generate_video(api_key, contents, settings, out_dir / "duration_15s.mp4")
        print(f"RESULT: 15s accepted. {result}")
        print(">>> Check reported_duration above — does it actually match 15, or did Kling truncate it?")
    except RuntimeError as exc:
        print(f"RESULT: 15s REJECTED — {exc}")
        print(">>> This confirms the code's own hedge that the real ceiling may be lower than 15s.")


def test_multichar(api_key: str, image_urls: list, out_dir: Path):
    print("\n=== TEST: multi-character cap (MAX_CHARACTERS_PER_VIDEO=3 assumption) ===")
    if len(image_urls) < 3:
        print("SKIPPED: needs at least 3 --reference-image-url values")
        return
    element_ids, names = [], []
    for i, url in enumerate(image_urls[:4]):
        name = f"TestChar{i+1}"
        eid = register_element(api_key, name, f"Test character {i+1}", url)
        element_ids.append(eid)
        names.append(name)
    prompt_parts = ", ".join(f"@{n}" for n in names)
    contents = [{"type": "prompt", "text": f"shot 1, 4, {prompt_parts}, standing together, neutral expressions.;"}]
    for i, eid in enumerate(element_ids):
        contents.append({"type": "element", "element_id": eid, "id": f"char_{i+1}"})
    settings = {"multi_shot": False, "audio": "off", "resolution": "1080p", "aspect_ratio": "9:16", "duration": 4}
    try:
        result = generate_video(api_key, contents, settings, out_dir / f"multichar_{len(element_ids)}.mp4")
        print(f"RESULT: {len(element_ids)} characters ACCEPTED. {result}")
    except RuntimeError as exc:
        print(f"RESULT: {len(element_ids)} characters REJECTED — {exc}")


def test_voice(api_key: str, voice_url: str):
    print("\n=== TEST: voice cloning registration ===")
    body = {"voice_name": "TestVoice"[:20], "voice_url": voice_url}
    resp = httpx.post(f"{_BASE}/v1/general/custom-voices", headers=_headers(api_key), json=body, timeout=30)
    data = _check(resp, "create_voice")
    _print_json("create_voice response", data)
    task_id = data["data"].get("task_id") or data["data"].get("id")
    import time
    for i in range(24):
        time.sleep(5)
        poll = httpx.get(f"{_BASE}/v1/general/custom-voices/{task_id}", headers=_headers(api_key), timeout=20)
        pdata = _check(poll, "create_voice poll")["data"]
        status = pdata.get("task_status", "")
        logger.info("  poll %d/24: task_status=%r", i + 1, status)
        if status in ("succeed", "succeeded"):
            _print_json("create_voice poll response", pdata)
            return
        if status == "failed":
            raise RuntimeError(f"Voice registration failed: {pdata.get('task_status_msg')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tests", default="auth,element,minimal,audio",
                         help="comma-separated: auth,element,minimal,audio,repeat,duration,multichar,voice,all")
    parser.add_argument("--reference-image-url", action="append", default=[],
                         help="a real character reference photo URL — repeat for multichar test")
    parser.add_argument("--voice-url", default=None, help="a real voice sample URL, for the voice test")
    parser.add_argument("--yes", action="store_true", help="required to run anything beyond 'auth' — this spends real money")
    parser.add_argument("--output-dir", default="kling_live_test_output")
    args = parser.parse_args()

    tests = set(args.tests.split(","))
    if "all" in tests:
        tests = {"auth", "element", "minimal", "audio", "repeat", "duration", "multichar", "voice"}

    api_key = _check_env()
    print("KLING_API_KEY is set. Running: auth check (free).")

    if tests == {"auth"}:
        print("Auth check only — KLING_API_KEY present. No API call made. Done.")
        return

    if not args.yes:
        logger.error(
            "Tests beyond 'auth' make real, billed Kling API calls. Re-run with --yes to confirm "
            "you want to spend real money, e.g.:\n"
            "  python scripts/live_test_kling_omni.py --yes --reference-image-url <url>"
        )
        sys.exit(1)

    if not args.reference_image_url and tests - {"auth", "voice"}:
        logger.error("--reference-image-url is required for every test except auth/voice")
        sys.exit(1)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    element_id = element_name = None
    if {"element", "minimal", "audio", "repeat", "duration"} & tests:
        element_name = "LiveTestChar"
        element_id = register_element(api_key, element_name, "A live-test character", args.reference_image_url[0])

    if "minimal" in tests:
        test_minimal(api_key, element_id, element_name, out_dir)
    if "audio" in tests:
        test_audio(api_key, element_id, element_name, out_dir)
    if "repeat" in tests:
        test_repeat(api_key, element_id, element_name, out_dir)
    if "duration" in tests:
        test_duration(api_key, element_id, element_name, out_dir)
    if "multichar" in tests:
        test_multichar(api_key, args.reference_image_url, out_dir)
    if "voice" in tests:
        if not args.voice_url:
            logger.error("--voice-url is required for the voice test")
        else:
            test_voice(api_key, args.voice_url)

    print(f"\nAll requested tests complete. Video output saved under {out_dir}/")


if __name__ == "__main__":
    main()
