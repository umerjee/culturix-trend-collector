"""Editorial review of a World video script: a 0-100 score, per-dimension scores, and concrete
improvement suggestions, before any paid render.

The toons section scores a script with an AI critic (culturetoon_script.judge_script_comedy) and lets
the user regenerate with that critic's feedback. World scripts get the same loop, but the rubric is
the one a short factual video is actually judged by: does it stop the scroll, build, MOVE, sound good
spoken aloud, show what it says, and stay true to its source.

Two dimensions (dynamism, narration) blend the critic's opinion with measurable properties of the
script, so a script full of still scenes cannot score well because a language model was generous. The
accuracy dimension is the existing fact-check (culturetoon_script.judge_world_grounding), not a second
opinion. Advisory: a low score never blocks anything, it tells the curator what to fix.
"""
import logging
from typing import Optional

from app.services.culturetoon_script import (
    _MOTION_WORDS, MIN_MOTION_WORDS, ToonScriptGenerationError, _call_llm_json, format_world_draft,
)

logger = logging.getLogger("culturix.services.world_review")

REVIEW_VERSION = 1
PASS_SCORE = 75
DIMENSION_FLOOR = 50
MAX_SUGGESTIONS = 5

# name -> (weight, what it measures). Weights sum to 100.
DIMENSIONS = {
    "hook": (20, "Opens on a striking moment, not a label"),
    "story": (20, "Builds and pays off instead of listing facts"),
    "dynamism": (25, "Something visibly happens and changes in every shot"),
    "narration": (15, "Vivid, concrete, natural to say aloud"),
    "visuals": (10, "Each picture shows what its line says"),
    "accuracy": (10, "Every claim is backed by the source"),
}

IDEAL_WORDS = (12, 20)


def _clamp(value, default: Optional[int] = None) -> Optional[int]:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def dynamism_signals(shots: Optional[list]) -> Optional[int]:
    """0-100 from what the script itself says about movement: how many action verbs each subject
    visual has, whether the camera moves, and whether camera and shot type vary. None with no shots."""
    subject = [s for s in (shots or []) if (s.get("shot_focus") or "subject").strip().lower() == "subject"]
    if not subject:
        return None
    motion = sum(
        min(1.0, len({m.group(0).lower() for m in _MOTION_WORDS.finditer(s.get("subject_visual") or "")}) / (MIN_MOTION_WORDS + 1))
        for s in subject) / len(subject)
    moving_camera = sum(1 for s in subject if (s.get("camera_movement") or "").strip().lower() not in ("", "static")) / len(subject)
    cameras = {(s.get("camera_movement") or "").strip().lower() for s in subject} - {""}
    types = {(s.get("shot_type") or "").strip().lower() for s in subject} - {""}
    variety = min(1.0, (len(cameras) + len(types)) / (2 * min(len(subject), 4)))
    return round(100 * (0.5 * motion + 0.25 * moving_camera + 0.25 * variety))


def narration_signals(shots: Optional[list]) -> Optional[int]:
    """0-100: the share of narration lines that are a speakable length (too short leaves the shot
    silent, too long forces a slow, static shot). None when there is no narration."""
    counts = [len((s.get("dialogue") or "").split()) for s in (shots or []) if (s.get("dialogue") or "").strip()]
    if not counts:
        return None
    low, high = IDEAL_WORDS
    return round(100 * sum(1 for c in counts if low <= c <= high) / len(counts))


def accuracy_signal(grounding: Optional[dict]) -> Optional[int]:
    """100 when fact-checked clean, 30 points off per unsupported claim, None if the check did not run."""
    if not grounding or grounding.get("grounded") is None:
        return None
    return max(0, 100 - 30 * len(grounding.get("unsupported_claims") or []))


def _prompt(script_result: dict, title: str, duration_seconds, source_facts: str, era: Optional[dict] = None) -> str:
    period = (f'\nThe video is set in {era["label"]}. Every object, building, garment and technology must have existed '
              "then and there.\n") if era and era.get("label") else ""
    return f"""You are a blunt, strict short-form video editor reviewing the script of a {duration_seconds}s factual video about "{title}".{period} Viewers scroll past anything slow, list-like or static. Most first drafts are mediocre; a score above 80 is rare and must be earned.

VERIFIED SOURCE MATERIAL (the only allowed source of facts):
{(source_facts or "").strip()[:1800]}

SCRIPT:
{format_world_draft(script_result)}

Score each dimension 0-100 with a one-sentence note that names the exact shot or line:
- hook: does shot 1's narration drop the viewer into a striking, specific moment (scale, odds, surprise) within three seconds? An encyclopedia opener ("X was a Y", "In 1944, ...") scores below 50 unless the fact itself is the shock.
- story: does it build (setup, escalation, turn, payoff), each line advancing cause and effect, and end on a line that reframes rather than summarises? A list of facts scores below 50.
- dynamism: in EVERY shot, do specific agents do physical things that visibly change between the first and last frame, with varied camera moves and scales? Ambient life ("people go about their day", "a bustling market", "villagers interacting", "smoke rises from chimneys") is NOT action: it is scenery. If most shots are ambient life or a scene that merely exists, score below 40 however many verbs it uses. A general standing on a platform addressing a crowd is a held frame.
- narration: vivid, concrete, natural to say aloud, about 14-18 words, no filler or stacked clauses.
- visuals: each picture shows what its narration line says at that moment, and is specific to this subject rather than generic stock.

Then give at most {MAX_SUGGESTIONS} suggestions, worst problem first. Each names the shot number (null for the whole video), the dimension, the problem, and a concrete fix that quotes replacement wording where possible. The opening is shot 1's narration line (there is no separate title): a hook problem is always shot 1, and its fix is a replacement line for shot 1. A visual problem's fix names one specific event. Never suggest adding a fact that is not in the source material.

List in "anachronisms" every object, building, garment, vehicle or technology in the script that did not exist in the period above (an empty list if none, or if no period is given).

Return ONLY valid JSON:
{{"dimensions": {{"hook": {{"score": int, "note": string}}, "story": {{...}}, "dynamism": {{...}}, "narration": {{...}}, "visuals": {{...}}}}, "suggestions": [{{"shot": int|null, "dimension": string, "issue": string, "fix": string}}], "anachronisms": [string], "summary": "one or two sentences: the overall verdict"}}"""


def _clean_suggestions(raw) -> list[dict]:
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        issue, fix = str(item.get("issue") or "").strip(), str(item.get("fix") or "").strip()
        if not issue or not fix:
            continue
        shot = item.get("shot")
        dimension = str(item.get("dimension") or "").strip().lower()
        out.append({"shot": int(shot) if isinstance(shot, (int, float)) and not isinstance(shot, bool) else None,
                    "dimension": dimension if dimension in DIMENSIONS else None,
                    "issue": issue[:300], "fix": fix[:400]})
        if len(out) == MAX_SUGGESTIONS:
            break
    return out


def review_world_script(script_result: dict, title: str, duration_seconds, source_facts: str,
                        grounding: Optional[dict] = None, era: Optional[dict] = None) -> dict:
    """Score a World script. Returns a dict that also carries the keys the toons UI/regenerate flow reads
    (comedy_score, passes_bar, feedback, judge_failed): {score, comedy_score, passes_bar, feedback,
    judge_failed, dimensions: {name: {score, weight, note}}, suggestions: [{shot, dimension, issue, fix}],
    review_version}. Fails open: if the critic call fails, score is None and only the measurable
    dimensions are filled in."""
    from app.services.world_era import find_anachronisms

    shots = script_result.get("shots")
    llm = {}
    llm_anachronisms: list = []
    summary = ""
    suggestions: list[dict] = []
    failed = False
    try:
        parsed = _call_llm_json(_prompt(script_result, title, duration_seconds, source_facts, era),
                                temperature=0.1, max_tokens=1100)
        llm = parsed.get("dimensions") or {}
        llm_anachronisms = [str(a).strip()[:80] for a in (parsed.get("anachronisms") or []) if str(a).strip()]
        summary = str(parsed.get("summary") or "").strip()
        suggestions = _clean_suggestions(parsed.get("suggestions"))
    except ToonScriptGenerationError as exc:
        logger.warning("World script review call failed, leaving the script unscored: %s", exc)
        failed = True

    def llm_score(name):
        entry = llm.get(name) if isinstance(llm.get(name), dict) else {}
        return _clamp(entry.get("score")), str(entry.get("note") or "").strip()

    # Period errors: the objects our own word lists know did not exist yet (certain), plus whatever the
    # critic noticed. Each one costs accuracy, and any one blocks a pass.
    anachronisms: list[str] = []
    for shot in shots or []:
        text = " ".join(str(shot.get(k) or "") for k in ("subject_visual", "visual", "location", "action"))
        anachronisms += [w for w in find_anachronisms(text, era) if w not in anachronisms]
    anachronisms += [a for a in llm_anachronisms if a.lower() not in {x.lower() for x in anachronisms}]
    anachronisms = anachronisms[:8] if (era and era.get("label")) else []

    dims: dict[str, dict] = {}
    for name, (weight, _) in DIMENSIONS.items():
        score, note = (None, "") if failed else llm_score(name)
        if name == "dynamism":
            measured = dynamism_signals(shots)
            score = measured if score is None else (score if measured is None else round(0.5 * score + 0.5 * measured))
        elif name == "narration":
            measured = narration_signals(shots)
            score = measured if score is None else (score if measured is None else round(0.6 * score + 0.4 * measured))
        elif name == "accuracy":
            score = accuracy_signal(grounding)
            if anachronisms:
                score = min(100 if score is None else score, max(0, 100 - 25 * len(anachronisms)))
                note = "Not from this period: " + ", ".join(anachronisms)
        dims[name] = {"score": score, "weight": weight, "note": note}

    scored = [d for d in dims.values() if d["score"] is not None]
    total_weight = sum(d["weight"] for d in scored)
    overall = None if failed or not total_weight else round(sum(d["score"] * d["weight"] for d in scored) / total_weight)
    passes = None
    if overall is not None:
        grounded = (grounding or {}).get("grounded")
        passes = (overall >= PASS_SCORE and all(d["score"] >= DIMENSION_FLOOR for d in scored)
                  and grounded is not False and not anachronisms)

    feedback = summary
    if suggestions:
        feedback = (feedback + " " if feedback else "") + "Fix first: " + suggestions[0]["issue"]
    return {
        "score": overall, "comedy_score": overall, "passes_bar": passes, "feedback": feedback or None,
        "judge_failed": failed, "dimensions": dims, "suggestions": suggestions, "review_version": REVIEW_VERSION,
        "anachronisms": anachronisms, "era": era if era and era.get("label") else None,
    }


def improvement_notes(review: dict, human_note: Optional[str] = None) -> list[str]:
    """The reviewer's suggestions (and an optional note typed by the curator) as one instruction each,
    for the writer's revision prompt."""
    notes = []
    for s in review.get("suggestions") or []:
        where = f"Shot {s['shot']}" if s.get("shot") else "Whole video"
        notes.append(f"{where}: {s['issue']} Fix: {s['fix']}")
    if human_note and human_note.strip():
        notes.append(f"The curator specifically asked: {human_note.strip()[:400]}")
    return notes


def review_view(judgment: Optional[dict]) -> Optional[dict]:
    """The part of a stored comedy_judgment the admin page shows, or None for a draft that predates this
    review (it has a toons-style score but no dimensions)."""
    if not judgment or "dimensions" not in judgment:
        return None
    return {k: judgment.get(k) for k in ("score", "passes_bar", "feedback", "judge_failed", "dimensions",
                                         "suggestions", "auto_improved", "first_score", "anachronisms", "era")}
