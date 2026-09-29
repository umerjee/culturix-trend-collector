"""QA for CultureToons — technical/visual deterministic checks (Phase 7a)
plus an AI-judge pass for comedy/cultural/story scoring (Phase 7b), see
docs/culturix-comedy-architecture.md §3.10 and §7.

Deliberately NOT a new Toon.status value — QA runs automatically right
after a successful generation and is stored as metadata (Toon.qa_results,
Toon.publish_recommended), layered on top of the existing "ready" status
rather than inserting a "qa" state into idea|animating|ready|posted|
archived|failed. publish_recommended is a soft signal only — the frontend
warns before publishing when it's False, but nothing here or in the publish
route hard-blocks it; a human always makes the final call.

2026-09-27: the vision-model gap described below is filled for World
Features by run_world_visual_qa (wired into
culturetoon_selfhosted_video.py's generate_video_for_toon_selfhosted,
which previously ran no QA of any kind — run_full_qa below is only ever
called from the Kling path in culturetoon_video.py). Built after a session
of manually downloading rendered World videos, extracting frames and
looking at them by hand to find real, confirmed hallucinations that a
passing script score never caught (a mantis shrimp rendered as a generic
shrimp, Seoul rendered as a coastal fishing village, a "running of the
bulls" video showing sheep, an avalanche video with no visible avalanche)
— every one of those has a script that read fine and scored above the
quality bar. The failure was never in the text, it was in what the video
model actually drew, which nothing was checking for.

Known limitation for ordinary CultureToons, stated plainly rather than
faked: "visual_score" in run_full_qa's shape was meant for real
visual-artifact detection (missing limbs, watermarks, character-
consistency drift) for a character-cast comedy skit — that still isn't
wired up here (run_world_visual_qa below is World-Feature-shaped: subject/
species/place fidelity against a script's shots, not character artifact
detection). visual_score in run_full_qa is still set equal to
technical_score, not an independent signal, for that path.
"""
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger("culturix.services.culturetoon_qa")

# Duration tolerance: Kling's actual output length isn't guaranteed to hit
# the requested duration to the frame (see culturetoon_clip_cutter.py's own
# docstring making the same point) — a fixed 2s floor plus 25% of the
# target avoids flagging every generation over a difference that's normal
# provider variance, not a real problem.
_DURATION_TOLERANCE_FLOOR_SECONDS = 2.0
_DURATION_TOLERANCE_RATIO = 0.25
_ASPECT_RATIO_TOLERANCE = 0.1

PUBLISH_OVERALL_THRESHOLD = 70
PUBLISH_CULTURAL_THRESHOLD = 60
PUBLISH_TECHNICAL_THRESHOLD = 50


def run_technical_qa(video_path: str, expected_duration_seconds: float, expected_aspect_ratio: str = "9:16") -> dict:
    """Deterministic, no LLM call — duration, aspect ratio, file integrity,
    audio-track presence. Reuses ffmpeg-python's probe() (same dependency
    culturetoon_clip_cutter.py already uses for duration probing), not a
    new dependency."""
    issues = []
    try:
        import ffmpeg
        info = ffmpeg.probe(video_path)
    except Exception as exc:
        return {
            "file_integrity_ok": False, "duration_ok": False, "aspect_ratio_ok": False, "audio_present": False,
            "technical_score": 0, "issues": [f"Failed to probe video file — likely corrupt or empty: {exc}"],
        }

    # If ffmpeg.probe() succeeded at all, the file is a well-formed
    # container — that's the file-integrity check.
    file_integrity_ok = True

    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    audio_present = len(audio_streams) > 0
    if not audio_present:
        issues.append("No audio track found")

    try:
        duration = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    tolerance = max(_DURATION_TOLERANCE_FLOOR_SECONDS, expected_duration_seconds * _DURATION_TOLERANCE_RATIO)
    duration_ok = abs(duration - expected_duration_seconds) <= tolerance
    if not duration_ok:
        issues.append(f"Duration {duration:.1f}s doesn't match the requested ~{expected_duration_seconds:.0f}s")

    aspect_ratio_ok = False
    if video_streams:
        width, height = video_streams[0].get("width"), video_streams[0].get("height")
        if width and height:
            try:
                expected_w, expected_h = (int(p) for p in expected_aspect_ratio.split(":"))
                actual_ratio = width / height
                expected_ratio = expected_w / expected_h
                aspect_ratio_ok = abs(actual_ratio - expected_ratio) / expected_ratio <= _ASPECT_RATIO_TOLERANCE
            except (ValueError, ZeroDivisionError):
                aspect_ratio_ok = False
        if not aspect_ratio_ok:
            issues.append(f"Video dimensions {width}x{height} don't match expected {expected_aspect_ratio} aspect ratio")
    else:
        issues.append("No video stream found")

    checks = [file_integrity_ok, duration_ok, aspect_ratio_ok, audio_present]
    technical_score = round(100 * sum(checks) / len(checks))

    return {
        "file_integrity_ok": file_integrity_ok, "duration_ok": duration_ok,
        "aspect_ratio_ok": aspect_ratio_ok, "audio_present": audio_present,
        "technical_score": technical_score, "issues": issues,
    }


def _build_judge_prompt(hook_line: str, tone: str, shots: list, cultures: list) -> str:
    shots_text = "\n".join(
        f"Shot {s.get('shot_number')}: {s.get('action', '')}"
        + (f' — "{s["dialogue"]}"' if s.get("dialogue") else "")
        for s in shots
    )
    culture_notes = ""
    if cultures:
        lines = []
        for c in cultures:
            avoid = "; ".join(c.get("stereotypes_to_avoid") or []) or "none listed"
            lines.append(f"- {c['name']}: explicitly avoid — {avoid}")
        culture_notes = "\nCultural guardrails for the cultures represented in this cast:\n" + "\n".join(lines)

    return f"""You are a QA reviewer for short character-based comedy skits. Score the
following script honestly and critically — do not default to high scores.

Hook: {hook_line or "(none)"}
Tone: {tone}
Shots:
{shots_text}
{culture_notes}

Return ONLY valid JSON with exactly these keys:
- comedy_score: integer 0-100, how funny/well-paced this actually is (not how funny it's trying to be)
- cultural_score: integer 0-100, 100 = fully respectful and free of demeaning stereotypes given the
  guardrails above, lower scores for any stereotype violation or demeaning portrayal, 0 = clearly
  offensive
- cultural_concerns: array of strings, specific issues found (empty array if none)
- reasoning: one sentence explaining the comedy_score

Return ONLY the JSON object, no other text."""


def _parse_judge_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def run_ai_judge_qa(hook_line: str, tone: str, shots: list, cultures: list) -> dict:
    """One LLM call (Qwen-max primary / Claude Haiku fallback, same pattern
    as every other generator in this codebase). Fails open to a neutral,
    clearly-flagged result rather than blocking the toon from reaching
    "ready" — a QA-judge outage must not stop generation from completing."""
    prompt = _build_judge_prompt(hook_line, tone, shots, cultures)
    try:
        if os.getenv("QWEN_API_KEY"):
            from openai import OpenAI
            qwen = OpenAI(api_key=os.environ["QWEN_API_KEY"], base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
            response = qwen.chat.completions.create(
                model="qwen-max", messages=[{"role": "user", "content": prompt}], temperature=0.3,
            )
            raw = response.choices[0].message.content
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            message = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        parsed = _parse_judge_response(raw)
        return {
            "comedy_score": int(parsed.get("comedy_score", 0)),
            "cultural_score": int(parsed.get("cultural_score", 0)),
            "cultural_concerns": parsed.get("cultural_concerns") or [],
            "reasoning": parsed.get("reasoning"),
            "judge_failed": False,
        }
    except Exception:
        logger.warning("AI-judge QA call failed, using a neutral placeholder result", exc_info=True)
        return {
            "comedy_score": 50, "cultural_score": 50, "cultural_concerns": [],
            "reasoning": "AI judge call failed — this is a neutral placeholder, not a real assessment.",
            "judge_failed": True,
        }


def run_full_qa(video_path: str, expected_duration_seconds: float, hook_line: str, tone: str,
                 shots: list, cultures: list, expected_aspect_ratio: str = "9:16") -> dict:
    """Combines technical (7a) and AI-judge (7b) checks into the spec's
    {visual_score, comedy_score, cultural_score, technical_score,
    overall_score, publish_recommended} shape. See module docstring for why
    visual_score is not an independent signal."""
    technical = run_technical_qa(video_path, expected_duration_seconds, expected_aspect_ratio)
    judge = run_ai_judge_qa(hook_line, tone, shots, cultures)

    technical_score = technical["technical_score"]
    visual_score = technical_score  # see module docstring — known limitation, not faked as independent
    comedy_score = judge["comedy_score"]
    cultural_score = judge["cultural_score"]
    overall_score = round((visual_score + comedy_score + cultural_score + technical_score) / 4)

    publish_recommended = (
        overall_score >= PUBLISH_OVERALL_THRESHOLD
        and cultural_score >= PUBLISH_CULTURAL_THRESHOLD
        and technical_score >= PUBLISH_TECHNICAL_THRESHOLD
    )

    issues = list(technical["issues"]) + list(judge["cultural_concerns"])
    if judge["judge_failed"]:
        issues.append("AI-judge scoring failed — comedy_score/cultural_score below are placeholders, not real assessments")

    return {
        "visual_score": visual_score, "comedy_score": comedy_score, "cultural_score": cultural_score,
        "technical_score": technical_score, "overall_score": overall_score,
        "publish_recommended": publish_recommended,
        "issues": issues, "reasoning": judge.get("reasoning"),
        "judge_failed": judge["judge_failed"],
    }


# ---- World Feature visual QA (2026-09-27) --------------------------------------------------------

WORLD_VISUAL_QA_FRAME_COUNT = 5
WORLD_PUBLISH_VISUAL_THRESHOLD = 60


def extract_video_frames(video_url: str, count: int = WORLD_VISUAL_QA_FRAME_COUNT) -> list[bytes]:
    """Downloads the rendered video and pulls `count` frames, evenly spaced across its
    duration, as JPEG bytes — the same manual download-and-look-at-frames process used all
    session to actually find these bugs, now automated. Raises on any failure (network,
    ffmpeg missing, corrupt file); the caller decides how to fail open."""
    import httpx

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg/ffprobe not available")
    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.mp4")
        resp = httpx.get(video_url, timeout=60)
        resp.raise_for_status()
        with open(video_path, "wb") as f:
            f.write(resp.content)

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30,
        )
        duration = float(probe.stdout.strip() or 0)
        if duration <= 0:
            raise RuntimeError(f"Could not read video duration (ffprobe: {probe.stderr.strip()})")

        frames = []
        # Evenly spaced, inset from the very first/last instant (a fade edge is not a
        # representative frame) — matches the sampling pattern used by hand all session.
        for i in range(count):
            timestamp = duration * (i + 0.5) / count
            frame_path = os.path.join(tmp, f"frame_{i}.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{timestamp:.2f}", "-i", video_path,
                 "-frames:v", "1", "-q:v", "3", frame_path],
                capture_output=True, timeout=30,
            )
            if os.path.exists(frame_path):
                with open(frame_path, "rb") as f:
                    frames.append(f.read())
        if not frames:
            raise RuntimeError("ffmpeg extracted no frames")
        return frames


def _build_world_visual_qa_prompt(subject_text: str, shots: list) -> str:
    shots_text = "\n".join(
        f"Shot {i + 1}: {(s.get('subject_visual') or s.get('visual') or s.get('dialogue') or '').strip()}"
        for i, s in enumerate(shots or [])
    )
    return f"""You are doing visual QA on an AI-generated short documentary video. The subject is:
{subject_text}

Attached are frames sampled evenly across the finished video, in order from start to end.
Here is what each shot's script called for it to show:
{shots_text}

STEP 1 -- before judging anything else, look ONLY at the frames (ignore the script text above)
and literally describe what creature/object/structure is actually visible: its class (animal,
plant, building, vehicle, natural feature...), and, if it's a living thing, distinguishing
features you can actually see (body shape, limbs vs fins vs wings, number of legs, covering --
fur/feathers/scales/skin, how it's moving). Write this as "subject_observed" -- a plain
description of what's on screen, not an interpretation of whether it's correct.

STEP 2 -- only now compare that literal description to the named subject ("{subject_text}") and
decide subject_matches. Confirmed live 2026-09-29: a flying-fish documentary's QA pass answered
subject_matches=true and never mentioned an identity problem, while the frames actually showed a
BIRD -- a rubber-stamped "yes" that skipped straight to judging motion/composition without ever
literally describing what kind of creature was on screen. Do not let a superficially plausible
scene (right habitat, right color, right general shape) pass as subject_matches=true; a bird
gliding over water is not a fish, a different building of the same era is not the named
landmark, a similar-looking species is not the named one. If STEP 1's description does not
clearly match the subject's real anatomy/identity, subject_matches MUST be false regardless of
how good the rest of the shot looks.

STEP 3 -- anatomy check, done separately from everything above and just as strictly: look at
EVERY person, animal or humanoid robot visible in EVERY frame (not just the main subject) and
count limbs, fingers and other paired features. AI video generation routinely renders extra,
missing, fused or duplicated limbs, extra fingers, or a second head/face blended into the frame
-- confirmed live 2026-09-29: a humanoid-robots documentary passed this whole check (subject
correct, actions matched the script) while a patient in Shot 1 had multiple limbs and the robot
itself had extra limbs, and nothing in the JSON ever flagged it because nothing was explicitly
asked to look. A scene can have the right subject doing the right action and still be broken
this way -- check it independently, do not assume anatomy is fine just because the subject and
action already passed. List every instance in "anatomical_issues" (which shot, who/what, what's
wrong) -- empty array only if you actually checked and found none.

Then check the rest, still against the actual frames, not the script:
- Does what's on screen match what each shot's script called for?
- Are there people, crowds or objects visible that the shots never described?
- If the subject's point is an extreme action (a strike, a fall, a collapse, extreme speed),
  is that action actually visible, or does the video stay calm throughout?

Return ONLY valid JSON with exactly these keys:
{{"subject_observed": "one or two sentences, plain description of what's literally visible, per STEP 1",
"subject_matches": boolean, "anatomical_issues": [string, empty array if none found after checking],
"shots_match_script": boolean, "unscripted_elements": [string],
"issues": [string, one per real problem found, specific and concrete — empty array if none],
"visual_score": integer 0-100, "reasoning": "one or two sentences explaining the score"}}"""


def run_world_visual_qa(video_url: str, subject_text: str, shots: list) -> dict:
    """The vision-model pass the module docstring above used to say wasn't wired into this
    codebase. Downloads the finished render, samples frames, and asks Claude (the one provider
    already configured everywhere else in this codebase for LLM calls — see
    culturetoon_script.py's _get_claude_client) whether the video actually shows what its own
    script says it shows. Fails open to a neutral, clearly-flagged result — a QA outage or a
    transient network error must never block a toon from reaching "ready"; the render itself
    already succeeded and cost real money."""
    try:
        frames = extract_video_frames(video_url)
    except Exception as exc:
        logger.warning("World visual QA: could not extract frames for %r: %s", subject_text, exc)
        return {
            "visual_score": 50, "subject_observed": None, "subject_matches": None, "anatomical_issues": [],
            "shots_match_script": None, "unscripted_elements": [], "issues": [f"Visual QA could not run: {exc}"],
            "reasoning": None, "judge_failed": True,
        }

    prompt = _build_world_visual_qa_prompt(subject_text, shots)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                      "data": base64.b64encode(frame).decode("ascii")}}
        for frame in frames
    ]
    content.append({"type": "text", "text": prompt})
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        # Upgraded from Haiku 4.5 to Sonnet 5 for this call specifically (2026-09-29) -- this is
        # the single check that decides whether the documentary shows the right subject at all,
        # and the cheaper model missed a bird rendered in place of a flying fish outright. One
        # call per successful render (not per attempt), so the cost increase is small and
        # bounded relative to what a wrong-subject video getting published would cost.
        message = client.messages.create(
            model="claude-sonnet-5", max_tokens=3000,
            messages=[{"role": "user", "content": content}],
        )
        # Confirmed live 2026-09-29: unlike the Haiku call this replaced, claude-sonnet-5
        # returned a ThinkingBlock as content[0] here, not text -- content[0].text (the pattern
        # every other Claude call in this codebase uses) broke outright. Find the actual text
        # block instead of assuming position 0, since that assumption no longer holds for this
        # model.
        text_block = next((b for b in message.content if getattr(b, "type", None) == "text"), None)
        if text_block is None:
            raise ValueError(f"No text block in Claude response (got: {[getattr(b, 'type', None) for b in message.content]})")
        parsed = _parse_judge_response(text_block.text)
        return {
            "visual_score": int(parsed.get("visual_score", 50)),
            "subject_observed": parsed.get("subject_observed"),
            "subject_matches": bool(parsed.get("subject_matches")),
            "anatomical_issues": parsed.get("anatomical_issues") or [],
            "shots_match_script": bool(parsed.get("shots_match_script")),
            "unscripted_elements": parsed.get("unscripted_elements") or [],
            "issues": parsed.get("issues") or [],
            "reasoning": parsed.get("reasoning"),
            "judge_failed": False,
        }
    except Exception:
        logger.warning("World visual QA call failed for %r, using a neutral placeholder result",
                       subject_text, exc_info=True)
        return {
            "visual_score": 50, "subject_observed": None, "subject_matches": None, "anatomical_issues": [],
            "shots_match_script": None, "unscripted_elements": [], "issues": [],
            "reasoning": "Visual QA call failed — this is a neutral placeholder, not a real assessment.",
            "judge_failed": True,
        }


def _build_prerender_risk_prompt(subject_text: str, shots: list) -> str:
    shots_text = "\n".join(
        f"Shot {i + 1}: {(s.get('subject_visual') or s.get('visual') or s.get('dialogue') or '').strip()}"
        for i, s in enumerate(shots or [])
    )
    return f"""You are doing a pre-render risk check on a script for an AI video generator, BEFORE any
paid GPU render happens. The subject is:
{subject_text}

Shots:
{shots_text}

This checks are based on real, confirmed failure patterns from many previous renders on this exact
pipeline (a photorealistic real-world-footage video model, no reference photo of the subject, text-
only conditioning). Judge this script against them, critically:

1. NO PHYSICAL FORM: is the subject itself something with no real-world physical existence to film —
   a video game, an app, a website, software, a purely virtual/digital thing? (Confirmed dead on
   arrival every time tried: Fortnite, Minecraft, Among Us, Roblox, Vine, all scored 5-15/100 on
   visual fidelity because there is nothing physical to point a camera at.) This is the single
   highest-confidence predictor of failure — if true, nothing else about the script matters.
2. UNANCHORED COMPLEX ACTION: does any shot describe a complex, multi-stage physical action (an
   animal leaping fully out of its environment to catch prey, a structure collapsing in a specific
   sequence) as a single vague clause, without breaking it into a clear, filmable before-state and
   after-state? (Confirmed failure: a shark script said "lunges out of water to catch a seal" and the
   render showed neither the lunge nor the seal, just calm water.)
3. NO DISTINGUISHING DESCRIPTOR: does a shot name an unusual/uncommon subject (an animal, an object)
   using only its bare name, with no color, shape, size or other visual descriptor at all, leaving a
   video model nothing to render besides a generic stand-in?

Return ONLY valid JSON: {{"high_risk": boolean, "risk_reasons": [string, specific and concrete, empty
if none], "recommendation": "render" or "do not render — rewrite first" or "do not render — subject
has no physical form to depict"}}"""


def assess_prerender_risk(subject_text: str, shots: list) -> dict:
    """Free (no GPU) pre-render check on the SCRIPT TEXT only, run before the render decision --
    catches what we've already confirmed fails, without paying to observe it fail again. Cannot
    catch everything run_world_visual_qa catches (that needs the actual frames), only the subset
    predictable from text: a subject with no physical form at all, a vague multi-stage action with
    no clear before/after, a subject named with no visual descriptor. Fails open (not high-risk) on
    any error -- a QA outage must not block a script that would have rendered fine."""
    prompt = _build_prerender_risk_prompt(subject_text, shots)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _parse_judge_response(message.content[0].text)
        return {
            "high_risk": bool(parsed.get("high_risk")),
            "risk_reasons": parsed.get("risk_reasons") or [],
            "recommendation": parsed.get("recommendation") or "render",
            "judge_failed": False,
        }
    except Exception:
        logger.warning("Pre-render risk check failed for %r, failing open (not high-risk)",
                       subject_text, exc_info=True)
        return {"high_risk": False, "risk_reasons": [], "recommendation": "render", "judge_failed": True}


def run_world_qa(video_url: str, expected_duration_seconds: float, subject_text: str, shots: list) -> dict:
    """Technical checks (reused as-is from run_technical_qa, which is already generic) plus
    the World-specific visual pass, combined into the same {overall_score,
    publish_recommended, issues} shape run_full_qa uses, so both write to Toon.qa_results/
    Toon.publish_recommended identically and the admin UI needs no World-specific branch."""
    import httpx

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "video.mp4")
        try:
            resp = httpx.get(video_url, timeout=60)
            resp.raise_for_status()
            with open(video_path, "wb") as f:
                f.write(resp.content)
            technical = run_technical_qa(video_path, expected_duration_seconds)
        except Exception as exc:
            technical = {"technical_score": 50, "issues": [f"Technical QA could not run: {exc}"]}

    visual = run_world_visual_qa(video_url, subject_text, shots)

    technical_score = technical["technical_score"]
    visual_score = visual["visual_score"]
    overall_score = round((technical_score + visual_score) / 2)
    anatomical_issues = visual.get("anatomical_issues") or []
    publish_recommended = (
        overall_score >= PUBLISH_OVERALL_THRESHOLD
        and visual_score >= WORLD_PUBLISH_VISUAL_THRESHOLD
        and technical_score >= PUBLISH_TECHNICAL_THRESHOLD
        and visual.get("subject_matches") is not False
        and visual.get("shots_match_script") is not False
        # Confirmed live 2026-09-29: a render with the right subject doing the right actions
        # still had a patient and a robot rendered with extra limbs -- an anatomical hallucination
        # is just as disqualifying as a wrong subject, and just as capable of hiding behind an
        # otherwise-passing score, so it gates the same hard way.
        and not anatomical_issues
    )
    issues = list(technical["issues"]) + list(visual["issues"])
    if anatomical_issues:
        issues.append("Anatomical issues: " + "; ".join(anatomical_issues))
    if visual.get("unscripted_elements"):
        issues.append("Unscripted elements visible: " + ", ".join(visual["unscripted_elements"]))
    if visual["judge_failed"]:
        issues.append("Visual QA judge call failed — visual_score below is a placeholder, not a real assessment")

    return {
        "visual_score": visual_score, "technical_score": technical_score, "overall_score": overall_score,
        "publish_recommended": publish_recommended, "issues": issues,
        "reasoning": visual.get("reasoning"), "judge_failed": visual["judge_failed"],
        "subject_observed": visual.get("subject_observed"),
        "subject_matches": visual.get("subject_matches"), "anatomical_issues": anatomical_issues,
        "shots_match_script": visual.get("shots_match_script"),
    }
