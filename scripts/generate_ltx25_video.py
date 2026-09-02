"""Generate an LTX-2.5 video: multi-character, native audio, NO LoRAs.

This is the proven-working recipe from the 2026-09-02 bring-up, preserved
as a runnable reference until it's folded into
app/services/culturetoon_selfhosted_video.py. The app itself still targets
LTX-2.3; this script is the only thing that drives 2.5 today.

Two things it demonstrates that change the product economics:

1. NO CHARACTER LoRAs. Identity is carried by image conditioning — LTX-2.5
   begins generation from a supplied first frame and propagates what's in
   it. For several characters, build a COMPOSITE anchor: each character's
   real portrait pasted side by side, ordered to match the blocking named
   in the prompt. That removes ~90 min of GPU training per character, and
   removes it permanently: LoRAs are version-locked, so every future LTX
   upgrade would otherwise mean retraining the whole cast.

2. Character attributes are read from the DATABASE, never invented.
   Confirmed the hard way: a hand-written prompt described Wen as a woman
   (characters.description says "A Chinese man...") and Hans as
   Scandinavian (it says German). Because 2.5 denoises audio jointly with
   video, a wrong description now produces a wrong VOICE too — on 2.3 that
   was impossible, since narration came from a separately chosen TTS voice.

Measured cost: ~$0.20-0.35 per video, ~200-230s execution, versus ~$2.00
and ~1600s on LTX-2.3 for worse output with no audio at all.

Usage:
    python scripts/generate_ltx25_video.py \
        --variants <uuid> <uuid> <uuid> \
        --background <uuid> \
        --out trio.mp4 [--duration 12]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
import time
from io import BytesIO

TARGET_W, TARGET_H = 1280, 704  # matches the model's own output geometry

# Deviations from the converted official template that are REQUIRED, both
# established empirically against the live endpoint:
#
#  - ResizeImageMaskNode is bypassed. Its `resize_type` is a
#    COMFY_DYNAMICCOMBO_V3: a {"value": ..., "longer_size": ...} dict passes
#    ComfyUI's validator but execution then dies with "execute() missing 1
#    required positional argument: 'resize_type'". Safe to drop because it
#    only resizes the input image before LTXVPreprocess, and this script
#    pre-sizes the anchor itself. Nothing in the sampling path changes.
#  - SaveVideo.format/codec are set explicitly; the converter's schema walk
#    doesn't surface them and execution reaches the final node and fails.
MAIN_CLIP = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"

NEGATIVE_PROMPT = (
    "blurry, out of focus, low quality, compression artifacts, ghosting, double exposure, "
    "motion smear, warped face, melted features, changing faces, inconsistent identity, "
    "distorted anatomy, deformed hands, extra limbs, extra fingers, disfigured, "
    "waxy skin, plastic skin, uncanny, flickering, watermark, text, caption, subtitles"
)


def load_cast(variant_ids: list) -> list:
    """Reads each character's REAL description from the database.

    The usable text lives on `characters.description` — every
    `character_variants.description` checked so far is empty and
    `culture_tag` is NULL, so joining through to the parent character is
    required, not optional."""
    import psycopg2

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(
        """
        select v.id, v.name, v.image_url, ch.description, v.culture_tag
        from character_variants v
        join characters ch on ch.id = v.character_id
        where v.id = any(%s::uuid[])
        """,
        ([str(v) for v in variant_ids],),
    )
    rows = {str(r[0]): r for r in cur.fetchall()}
    conn.close()

    cast = []
    for vid in variant_ids:
        row = rows.get(str(vid))
        if not row:
            raise SystemExit(f"character variant {vid} not found")
        _id, name, image_url, description, culture_tag = row
        if not description:
            raise SystemExit(
                f"{name} has no characters.description — the prompt must not invent one "
                "(that is how a male character ended up with a female voice)"
            )
        cast.append({"id": str(_id), "name": name, "image_url": image_url,
                     "description": description.strip(), "culture_tag": culture_tag})
    return cast


def load_background(background_id: str) -> dict | None:
    import psycopg2

    if not background_id:
        return None
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(
        "select name, description, country, visual_style from toon_backgrounds where id = %s",
        (background_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"name": row[0], "description": row[1], "country": row[2], "visual_style": row[3]}


def build_anchor(cast: list) -> bytes:
    """Composites every cast member's real portrait into ONE first frame.

    Image conditioning propagates whatever the first frame contains, so
    every identity that must persist has to be present here — a single
    portrait can only ever carry one face. Slots run left to right so the
    model's spatial reading agrees with the blocking in the prompt."""
    import httpx
    from PIL import Image

    canvas = Image.new("RGB", (TARGET_W, TARGET_H), (28, 24, 22))
    slot_w = TARGET_W // len(cast)
    for i, member in enumerate(cast):
        img = Image.open(BytesIO(httpx.get(member["image_url"], timeout=60).content)).convert("RGB")
        # Cover-fit into the slot; crop rather than stretch so faces keep
        # their proportions.
        scale = max(slot_w / img.width, TARGET_H / img.height)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
        left, top = (img.width - slot_w) // 2, (img.height - TARGET_H) // 2
        canvas.paste(img.crop((left, top, left + slot_w, top + TARGET_H)), (i * slot_w, 0))
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def build_prompt(cast: list, background: dict | None, shots: list) -> str:
    """Composes a cinematic brief from REAL data.

    Structure validated by the first good result: the set described as
    built (props/materials), lighting with DIRECTION (what actually holds
    continuity across cuts), blocking by position with a prop per
    character (props keep people readable when faces drift), one named
    camera move per shot, dialogue carrying delivery, and an explicit
    identity constraint — in a no-LoRA setup that constraint plus the
    negative prompt is the only thing enforcing identity."""
    positions = ["LEFT", "CENTRE", "RIGHT", "FAR RIGHT"]
    parts = []

    if background:
        setting = f"{background['name']}"
        if background.get("country"):
            setting += f", in {background['country']}"
        parts.append(f"Setting: {setting}.")
        if background.get("description"):
            parts.append(background["description"])
    parts.append(f"{len(cast)} characters share the scene, seated together and facing camera.")

    for i, member in enumerate(cast):
        pos = positions[i] if i < len(positions) else f"POSITION {i+1}"
        line = f"{pos}: {member['description']}"
        if member.get("culture_tag"):
            line += f" ({member['culture_tag']})"
        parts.append(line)

    for i, shot in enumerate(shots, start=1):
        lead = "SHOT 1" if i == 1 else f"CUT TO SHOT {i}"
        seg = f"{lead} — {shot['shot_type']}, camera {shot['camera']}: {shot['action']}"
        if shot.get("dialogue"):
            delivery = f", {shot['delivery']}" if shot.get("delivery") else ""
            seg += f' {shot["speaker"]} says{delivery}: "{shot["dialogue"]}"'
        parts.append(seg)

    parts.append(
        "Consistent character appearance throughout, faces matching the opening frame exactly. "
        "Natural facial performance and lip movement synced to the dialogue. "
        "Cinematic lighting with clear direction, shallow depth of field, stable features, "
        "sharp focus, film-quality render."
    )
    return " ".join(parts)


def prepare_workflow(workflow_path: str, prompt: str, duration_seconds: int) -> dict:
    with open(workflow_path, "r", encoding="utf-8") as f:
        wf = json.load(f)

    def find(cls):
        return [nid for nid, n in wf.items() if n["class_type"] == cls]

    for nid in find("PrimitiveStringMultiline"):
        if isinstance(wf[nid]["inputs"].get("value"), str):
            wf[nid]["inputs"]["value"] = prompt
    for nid in find("CLIPTextEncode"):
        if isinstance(wf[nid]["inputs"].get("text"), str):
            wf[nid]["inputs"]["text"] = NEGATIVE_PROMPT
    for nid in find("PrimitiveInt"):
        if wf[nid]["inputs"].get("value") == 5:      # template's default duration
            wf[nid]["inputs"]["value"] = duration_seconds
    # A fresh seed each run, or ComfyUI's execution cache returns a prior result.
    for nid in find("RandomNoise"):
        if isinstance(wf[nid]["inputs"].get("noise_seed"), int):
            wf[nid]["inputs"]["noise_seed"] = random.randint(1, 2**31 - 1)
    # The optional prompt-enhancer CLIP isn't downloaded; point every loader
    # at the main encoder and keep enhancement off so it stays inert.
    for nid in find("CLIPLoader"):
        wf[nid]["inputs"]["clip_name"] = MAIN_CLIP
    for node in wf.values():
        if node["class_type"] == "PrimitiveBoolean" and isinstance(node["inputs"].get("value"), bool):
            node["inputs"]["value"] = False
    for nid in find("LoadImage"):
        wf[nid]["inputs"]["image"] = "reference.png"

    for nid in find("ResizeImageMaskNode"):      # see module docstring
        src = wf[nid]["inputs"].get("input")
        for other in wf.values():
            for key, val in list(other["inputs"].items()):
                if isinstance(val, list) and len(val) == 2 and str(val[0]) == str(nid):
                    other["inputs"][key] = src
        del wf[nid]
    for nid in find("SaveVideo"):
        wf[nid]["inputs"].setdefault("format", "auto")
        wf[nid]["inputs"].setdefault("codec", "auto")
    return wf


def submit(workflow: dict, anchor: bytes, timeout_seconds: int = 2700) -> bytes:
    import httpx

    endpoint = os.environ["RUNPOD_SERVERLESS_ENDPOINT_ID"]
    headers = {"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}",
               "Content-Type": "application/json"}
    payload = {"input": {"workflow": workflow,
                         "reference_image_base64": base64.b64encode(anchor).decode("ascii")}}

    job = None
    for attempt in range(8):
        resp = httpx.post(f"https://api.runpod.ai/v2/{endpoint}/run",
                          headers=headers, json=payload, timeout=120)
        # RunPod returns 409 for a while after any endpoint config change;
        # that's a settling window, not a failure.
        if resp.status_code == 409:
            print(f"  409 Conflict (endpoint settling), retry {attempt + 1}/8")
            time.sleep(20)
            continue
        resp.raise_for_status()
        job = resp.json()["id"]
        break
    if not job:
        raise SystemExit("endpoint never accepted the job (persistent 409)")
    print("job:", job)

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(20)
        status = httpx.get(f"https://api.runpod.ai/v2/{endpoint}/status/{job}",
                           headers=headers, timeout=30).json()
        state = status.get("status")
        print(" ", state, flush=True)
        if state == "COMPLETED":
            out = status.get("output") or {}
            if "error" in out:
                raise SystemExit(f"handler error: {str(out['error'])[:2000]}")
            print(f"  execution: {(status.get('executionTime') or 0) / 1000:.0f}s")
            return base64.b64decode(out["video_base64"])
        if state == "FAILED":
            err = str(status.get("error") or "")
            marker = err.find("exception_message")
            raise SystemExit(f"job failed: {err[marker:marker + 500] if marker > 0 else err[:1500]}")
    raise SystemExit("timed out waiting for the job")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", nargs="+", required=True, help="character_variant UUIDs, in left-to-right order")
    parser.add_argument("--background", help="toon_background UUID")
    parser.add_argument("--out", default="ltx25.mp4")
    parser.add_argument("--duration", type=int, default=12)
    parser.add_argument(
        "--workflow",
        default=os.path.join(os.path.dirname(__file__), "..", "app", "media", "workflows",
                             "ltx25_image_to_video.api.json"),
    )
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    cast = load_cast(args.variants)
    background = load_background(args.background)
    print("Cast (descriptions read from the database, never invented):")
    for member in cast:
        print(f"  {member['name']}: {member['description'][:90]}")
    if background:
        print(f"Location: {background['name']} ({background.get('country')})")

    # Placeholder beats. Real integration should take these from
    # ToonScript.shots rather than hardcoding them here.
    shots = [
        {"shot_type": "wide establishing shot", "camera": "slowly pushing in",
         "action": f"{cast[0]['name']} turns a laptop toward the others, brow furrowed.",
         "speaker": cast[0]["name"], "dialogue": "This is not the king I searched for.",
         "delivery": "deadpan"},
        {"shot_type": "medium two-shot", "camera": "static",
         "action": f"{cast[min(1, len(cast)-1)]['name']} leans in to look at the screen, eyebrows lifting.",
         "speaker": cast[min(1, len(cast) - 1)]["name"], "dialogue": "That is a goat wearing a crown.",
         "delivery": "incredulous"},
        {"shot_type": "close up", "camera": "drifting slowly right",
         "action": f"{cast[-1]['name']} looks up, then breaks into laughter.",
         "speaker": cast[-1]["name"], "dialogue": "Honestly, better king.",
         "delivery": "delighted"},
        {"shot_type": "wide shot", "camera": "pulling back to the establishing frame",
         "action": "all of them laughing together, the laptop glowing between them.",
         "speaker": None, "dialogue": None},
    ]

    prompt = build_prompt(cast, background, shots)
    print(f"\nprompt ({len(prompt)} chars):\n{prompt[:400]}...\n")

    anchor = build_anchor(cast)
    print(f"composite anchor: {len(anchor)} bytes ({len(cast)} portraits)")

    workflow = prepare_workflow(os.path.abspath(args.workflow), prompt, args.duration)
    video = submit(workflow, anchor)
    with open(args.out, "wb") as f:
        f.write(video)
    print(f"SUCCESS: {len(video)} bytes -> {args.out}")


if __name__ == "__main__":
    main()
