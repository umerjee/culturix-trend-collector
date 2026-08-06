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

Known limitation, stated plainly rather than faked: "visual_score" in the
spec's original shape was meant for real visual-artifact detection (missing
limbs, watermarks, character-consistency drift) — that requires a
vision-model pass over actual video frames, which isn't wired into this
codebase. visual_score here is set equal to technical_score (a file that
probes cleanly at least isn't corrupt/truncated), not an independent
signal. Don't read a high visual_score as "a human confirmed the video
looks right" — nobody/nothing has looked at it.
"""
import json
import logging
import os

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
