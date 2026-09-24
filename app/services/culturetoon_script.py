"""Trend-tied script generation for CultureToons — combines
clip_script.py's Persona/Cluster context-branching with
shopify/content_ideas.py's structured-JSON-output pattern. Same Qwen-max
primary / Claude Haiku fallback provider pattern as every other content
generator in this codebase.

Scripts are shot-structured (a list of {shot_number, duration_seconds,
action, expression, dialogue}), not a single flat hook/dialogue/scene blob —
this is what lets build_kling_prompt() assemble Kling Omni's multi-shot DSL
("shot n,m,words; shot n,m,words;") directly from a stored script, once a
CharacterVariant has been registered as a Kling Element (see
app/media/kling_omni.py / app/services/culturetoon_element.py).
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from itertools import zip_longest
from typing import Optional

from app.models.persona import Persona
from app.models.cluster import Cluster
from app.models.toon_shot import SHOT_TYPES, CAMERA_MOVEMENTS

logger = logging.getLogger("culturix.services.culturetoon_script")

# How far back to look, per brand, when deciding whether a ranked trend has
# already been used for a script — keeps run_culturetoon_trend_dispatch (see
# app/scheduler.py) from redrafting the exact same Persona/Cluster every time
# it runs for a brand.
TREND_DEDUP_LOOKBACK_DAYS = 14

# Duplicated from app/routers/culturetoons.py's EXPRESSION_NAMES rather than
# imported — a service importing from a router would run the dependency
# direction backwards, and this codebase already has precedent for small
# duplicated constants/helpers over that kind of coupling (e.g.
# clips.py::_fetch_source / culturetoons.py::_fetch_trend_source).
EXPRESSION_NAMES = [
    "Angry", "Confused", "Happy", "Shocked", "Laughing",
    "Side-eye", "Crying", "Annoyed", "Smiling", "Deadpan",
]

TONE_OPTIONS = [
    "funny", "dramatic", "satiric", "sad", "wholesome", "chaotic", "deadpan",
    # Informative registers, for brands whose content teaches rather than
    # jokes (explainers, tutorials, analysis). See INFORMATIVE_TONES.
    "educational", "explainer", "informative", "inspirational",
]

# Tones whose job is to make the viewer UNDERSTAND something, not to land a
# joke. Everything downstream that assumes comedy has to branch on this: the
# writer's craft directives, its worked example, and the judge's rubric.
# Adding an "educational" option without this would produce comedy skits
# wearing an educational label, then have a comedy critic fail them for not
# being funny — the option would look supported while being unusable.
INFORMATIVE_TONES = {"educational", "explainer", "informative", "inspirational"}

# Natural conversational delivery, in words per second. LTX-2.5 fits whatever
# line it is given into the shot's duration, so an over-long line is not
# truncated — it is rushed. Measured on live scripts before this existed:
# shots ran at 3-7 w/s, one at 7.3, which is what "talking too fast" was.
SPEECH_WORDS_PER_SECOND = 2.5

# Extra seconds given to the shot carrying the LAST spoken line in the whole
# script, on top of what its word count alone needs. Every other shot's line
# can run a little long into the cut to the next shot and it's barely
# noticeable; the closing line has nothing after it to bleed into, so fitting
# it to the word budget exactly means it gets cut off right as the last word
# lands, with no room for the natural trailing consonant/breath. Confirmed
# live 2026-09-02: Hans's closing line was audibly clipped at the very end.
CLOSING_LINE_BREATH_SECONDS = 1

# What the CAMERA is on in a shot. Before this, every shot was implicitly
# "character": the schema described blocking, action and expression and
# nothing else, so a script could not express a shot of the SUBJECT — the
# black hole, the game world, the product — and every video came out as a
# talking head in front of a background.
SHOT_FOCUS_TYPES = ["character", "subject", "both"]

# Ceiling on how many distinct physical locations plan_scenes() may plan for
# one script — a cost/complexity backstop, not a target. The actual count
# for any given script is theme-driven and almost always lower (see
# plan_scenes' own docstring) — never treat this as how many scenes a
# script "should" have.
MAX_PLANNED_SCENES = 4


def dialogue_word_budget(duration_seconds) -> int:
    """Words that fit in a shot at natural pace. Floor of 3 so a very short
    shot still allows a real line rather than a single word."""
    try:
        seconds = float(duration_seconds or 0)
    except (TypeError, ValueError):
        seconds = 0
    return max(3, int(seconds * SPEECH_WORDS_PER_SECOND))


def fit_shot_durations(shots: list, max_total: Optional[int] = None) -> list:
    """Extends any shot whose line cannot be said in its own duration.

    The writer prompt states the word budget per shot with worked arithmetic,
    and the model still overruns it — measured on two consecutive drafts of
    the same script, 7/7 then 6/7 shots over, even with an explicit
    correction naming the exact limits. LLMs do not count reliably, so this
    stops asking and computes it: a line is never rewritten, the shot is
    simply given the seconds it needs.

    Growth is bounded by max_total (MAX_TOTAL_SECONDS by default) because
    duration is what a render costs. Shots that cannot be extended inside
    that budget keep their original duration and stay visible through
    overlong_shots(), rather than silently pushing the video over its ceiling.
    """
    import math

    limit = MAX_TOTAL_SECONDS if max_total is None else max_total
    fitted = [dict(shot or {}) for shot in shots or []]
    total = sum(s.get("duration_seconds") or 0 for s in fitted)

    for shot in fitted:
        words = len((shot.get("dialogue") or "").split())
        if not words:
            continue
        current = shot.get("duration_seconds") or 0
        needed = max(1, math.ceil(words / SPEECH_WORDS_PER_SECOND))
        extra = needed - current
        if extra <= 0:
            continue
        if total + extra > limit:
            logger.warning(
                "Shot %s needs %ds for %d words but the script is at %ds/%ds — left rushed",
                shot.get("shot_number"), needed, words, total, limit,
            )
            continue
        shot["duration_seconds"] = needed
        total += extra

    closing_shots = [s for s in fitted if (s.get("dialogue") or "").strip()]
    if closing_shots:
        closer = closing_shots[-1]
        words = len(closer["dialogue"].split())
        current = closer.get("duration_seconds") or 0
        needed = max(1, math.ceil(words / SPEECH_WORDS_PER_SECOND)) + CLOSING_LINE_BREATH_SECONDS
        extra = needed - current
        if extra > 0:
            if total + extra > limit:
                logger.warning(
                    "Closing shot %s needs %ds (incl. trailing breath) for %d words but the "
                    "script is at %ds/%ds — closing line left without breathing room",
                    closer.get("shot_number"), needed, words, total, limit,
                )
            else:
                closer["duration_seconds"] = needed
    return fitted


def overlong_shots(shots: list) -> list:
    """Shots whose dialogue cannot be delivered in their own duration.
    Advisory — surfaced to the user, never silently rewritten."""
    flagged = []
    for shot in shots or []:
        words = len((shot.get("dialogue") or "").split())
        budget = dialogue_word_budget(shot.get("duration_seconds"))
        if words > budget:
            flagged.append({
                "shot_number": shot.get("shot_number"),
                "words": words,
                "budget": budget,
                "seconds": shot.get("duration_seconds"),
            })
    return flagged


def is_informative_tone(tone: Optional[str]) -> bool:
    return (tone or "").strip().lower() in INFORMATIVE_TONES

# Public (no leading underscore) — app/routers/culturetoons.py validates
# user-supplied num_shots/target_duration_seconds against these before
# calling the LLM, so an out-of-range request 400s immediately instead of
# failing later inside build_kling_prompt after already spending a call.
#
# A script itself is provider-agnostic (self-hosted just flattens shots
# into one continuous prompt, no per-shot DSL — see
# culturetoon_selfhosted_video.py's build_prompt_from_script), so these are
# the general script-creation ceiling, raised to cover real short-form
# social durations (15s/30s/60s — see ScriptManager.tsx's DURATION_PRESETS)
# now that self-hosted has no per-call duration limit in code. Kling Omni's
# own, much lower, real ceiling is KLING_MAX_SHOTS/KLING_MAX_TOTAL_SECONDS
# below — a script written for a 60s self-hosted clip still can't be
# rendered via Kling, enforced separately at generate-time.
MIN_SHOTS = 2
# Raised for explainers 2026-09-02. A skit lands in 15-30s, but an
# explainer needs room to state a problem, give the mechanism and land the
# consequence — and now that fit_shot_durations paces lines properly,
# duration is set by how much there is to SAY rather than trimmed to fit an
# arbitrary ceiling.
#
# The binding constraint is render time, not the script. Measured on real
# renders: 12s took 226s of GPU and 40s took ~728s, so roughly 18.3 GPU
# seconds per second of output. 180s of video is therefore ~55 minutes of
# GPU and about $4 — which is why the client and worker job timeouts had to
# move with this number. See RENDER_GPU_SECONDS_PER_OUTPUT_SECOND.
MAX_SHOTS = 30
MIN_TOTAL_SECONDS = 3
MAX_TOTAL_SECONDS = 180
# Kling Omni's real (unverified-but-assumed, see this module's own history)
# per-call ceiling — used by build_kling_prompt below and by the router's
# provider-specific check in generate_toon_video. Unchanged from the
# original MAX_SHOTS/MAX_TOTAL_SECONDS values before self-hosted needed its
# own, larger, general ceiling above.
KLING_MAX_SHOTS = 6
KLING_MAX_TOTAL_SECONDS = 15
_MAX_SHOT_PROMPT_CHARS = 512


class ToonScriptGenerationError(Exception):
    pass


def _get_qwen_client():
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["QWEN_API_KEY"],
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )


def _get_claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _source_type_and_context(persona_or_cluster) -> tuple[str, str]:
    if isinstance(persona_or_cluster, Persona):
        p = persona_or_cluster
        return "persona", (
            f"Persona name: {p.name}\n"
            f"Description: {p.description}\n"
            f"Motivations: {p.motivations or 'n/a'}\n"
            f"Interests: {p.interests or 'n/a'}"
        )
    c = persona_or_cluster
    return "cluster", (
        f"Trend theme: {c.theme or 'n/a'}\n"
        f"Summary: {c.summary or 'n/a'}"
    )


def select_trend_for_brand(session, brand):
    """Picks the best real-world trend to ground an auto-drafted script in,
    for run_culturetoon_trend_dispatch (app/scheduler.py). Same candidate
    pool and ranking as GET /trend-sources (app/routers/culturetoons.py):
    active Personas + recent Clusters, ranked by relevance to
    brand.trend_interests when set, else left in recency order — fails open
    to unranked on any embedding error, same convention as the endpoint.

    Personas and Clusters are two independently-ranked lists (relevance
    scores aren't comparable across the two without re-deriving raw cosine
    values, which rank_by_relevance intentionally doesn't expose), so
    they're interleaved best-of-each rather than merged by score — a simple,
    defensible way to avoid one type systematically crowding out the other.

    Filters out any (source_type, source_id) this brand already has a
    ToonScript for within TREND_DEDUP_LOOKBACK_DAYS, so the same trend isn't
    redrafted every dispatch run. If every ranked candidate has already been
    used, falls back to the single top-ranked one anyway (a repeat is better
    than no draft at all).

    Returns (source_type, source_id, source_obj), or None if the brand has
    no active Personas/Clusters to draw on at all."""
    from app.models.toon_script import ToonScript

    personas = (
        session.query(Persona).filter(Persona.status == "active")
        .order_by(Persona.updated_at.desc()).limit(50).all()
    )
    clusters = (
        session.query(Cluster).order_by(Cluster.updated_at.desc()).limit(50).all()
    )

    if brand.trend_interests:
        try:
            from app.services.culturetoon_trend_relevance import get_interests_embedding, rank_by_relevance
            interests_embedding = get_interests_embedding(brand)
            personas = rank_by_relevance(session, personas, lambda p: f"{p.name}. {p.description}", interests_embedding)
            clusters = rank_by_relevance(session, clusters, lambda c: f"{c.theme or ''}. {c.summary or ''}", interests_embedding)
            session.commit()
        except Exception:
            session.rollback()
            logger.warning(
                "Trend relevance ranking failed for brand %s auto-dispatch, falling back to recency", brand.id, exc_info=True,
            )

    candidates = []
    for p, c in zip_longest(personas, clusters):
        if p is not None:
            candidates.append(("persona", p.id, p))
        if c is not None:
            candidates.append(("cluster", c.id, c))
    if not candidates:
        return None

    cutoff = datetime.utcnow() - timedelta(days=TREND_DEDUP_LOOKBACK_DAYS)
    used = set(
        session.query(ToonScript.source_type, ToonScript.source_id)
        .filter(
            ToonScript.brand_id == brand.id,
            ToonScript.created_at >= cutoff,
            ToonScript.source_type.isnot(None),
        )
        .all()
    )

    for source_type, source_id, source_obj in candidates:
        if (source_type, source_id) not in used:
            return source_type, source_id, source_obj

    logger.info(
        "All ranked trends already used by brand %s within %dd, repeating top choice",
        brand.id, TREND_DEDUP_LOOKBACK_DAYS,
    )
    return candidates[0]


def _personality_line(v, character_personalities: Optional[dict]) -> str:
    """Renders one variant's parent Character.personality (traits/
    behavioral_rules/speech_rules — see docs/culturix-comedy-architecture.md
    §3.2) as a short inline clause, or "" if no personality is set. Keeping
    character identity deterministic across scripts is the whole point of
    this field existing — without it, the LLM re-improvises personality
    from scratch (or from the vaguer free-text description) every single
    call."""
    if not character_personalities:
        return ""
    personality = character_personalities.get(str(getattr(v, "character_id", "")))
    if not personality:
        return ""
    bits = []
    traits = personality.get("traits") or {}
    if traits:
        top_traits = sorted(traits.items(), key=lambda kv: kv[1], reverse=True)[:4]
        bits.append("traits: " + ", ".join(f"{name} ({value:.1f})" for name, value in top_traits))
    if personality.get("behavioral_rules"):
        bits.append("always: " + "; ".join(personality["behavioral_rules"]))
    if personality.get("speech_rules"):
        bits.append("speech style: " + "; ".join(personality["speech_rules"]))
    return f" [{'; '.join(bits)}]" if bits else ""


def _cast_line(variants: list, source_type: str, character_personalities: Optional[dict] = None) -> str:
    """variants: a list of CharacterVariant-like objects (may be empty).
    Single-character phrasing is kept as its own branch (not just a 1-item
    version of the multi-character one) since it reads more naturally and
    matches this prompt's original, already-tested wording. The
    multi-character branch requires the model to name a REAL character per
    shot via "speaker_name" rather than inventing one — this is the direct
    fix for a script inventing a fictional second character (e.g. a "Marvel
    purist") when only one real variant was ever supplied.

    character_personalities: optional {character_id: personality_dict} —
    see _personality_line. Keyed by Character.id (the base character), not
    CharacterVariant.id, since personality lives on the base Character and
    is shared across its cultural variants."""
    if not variants:
        return ""
    if len(variants) == 1:
        v = variants[0]
        return (
            f"\nWrite this specifically for the character '{v.name}' "
            f"({v.description or v.culture_tag or 'no further description'})"
            f"{_personality_line(v, character_personalities)}. "
            f"Every shot's action/dialogue must be something THIS character does/says, "
            f"reacting to the {source_type} below in a way that reflects their cultural humor/perspective.\n"
        )
    cast_block = "\n".join(
        f"- '{v.name}' ({v.description or v.culture_tag or 'no further description'})"
        f"{_personality_line(v, character_personalities)}"
        for v in variants
    )
    return f"""
This is a scene between these {len(variants)} REAL characters — do not invent any other
character, and every character who appears must be one of these:
{cast_block}
Write actual back-and-forth dialogue/interaction between them, each reacting to the
{source_type} below in a way that reflects their own individual cultural humor/perspective.
Every shot's "speaker_name" must be the exact name of whichever one of these characters is
acting/speaking in that shot.
"""


def _memory_context(memories: Optional[list]) -> str:
    """memories: list of memory content strings, already retrieved/filtered
    by app/services/culturetoon_memory.py::retrieve_relevant_memories for
    relevance to this script's context — see
    docs/culturix-comedy-architecture.md §3.5. Empty string if none."""
    if not memories:
        return ""
    lines = "\n".join(f"- {m}" for m in memories)
    return f"\nRelevant things that happened before, from this character's history (reference naturally if it fits, don't force it):\n{lines}\n"


def _culture_context(cultures: Optional[list]) -> str:
    """cultures: list of serialized Culture dicts (see
    app/models/culture.py — deduped, one per distinct culture actually
    present in the cast, resolved from each variant's culture_id). Surfaces
    real comedy material (common_misunderstandings, positive_traits) AND an
    explicit avoid-list (stereotypes_to_avoid) in the same breath — the
    culture library exists specifically so cultural humor doesn't default
    to demeaning generalizations, per docs/culturix-comedy-architecture.md
    §11/§3.7."""
    if not cultures:
        return ""
    lines = []
    for c in cultures:
        parts = [f"{c['name']}:"]
        if c.get("humor_sensitivity"):
            parts.append(c["humor_sensitivity"])
        if c.get("common_misunderstandings"):
            parts.append("Material to draw on: " + "; ".join(c["common_misunderstandings"]))
        if c.get("positive_traits"):
            parts.append("Positive traits to reflect: " + ", ".join(c["positive_traits"]))
        if c.get("stereotypes_to_avoid"):
            parts.append("AVOID: " + "; ".join(c["stereotypes_to_avoid"]))
        lines.append("- " + " ".join(parts))
    return "\nCultural context (use for authentic material, respect the AVOID guidance strictly):\n" + "\n".join(lines) + "\n"


def _relationship_context(relationships: Optional[list]) -> str:
    """relationships: list of serialized CharacterRelationship dicts (see
    app/routers/culturetoons.py::resolve_relationships_for_cast) — already
    filtered to the pair(s) actually present in this script's cast. Each
    dict carries a "directions" list (exactly 2 entries: A->B and B->A —
    see CharacterRelationshipDirection) since personality toward another
    character isn't necessarily symmetrical (Kumar's feelings about Hans
    can differ from Hans's about Kumar), each direction optionally naming
    from_character_name/to_character_name (attached by the resolver, not
    part of the direction's normal serialization) so the prompt can name
    names instead of UUIDs. Also optionally carries a "recent_events" list
    (the relationship's own history log, see CharacterRelationshipEvent —
    newest first, already capped to a handful by the resolver). Empty
    string if none, so a single-character script or a cast with no stored
    relationship doesn't get a dangling empty section in the prompt."""
    if not relationships:
        return ""
    lines = []
    for r in relationships:
        header = []
        type_label = r.get("relationship_type_label") or (r.get("relationship_type") or "").replace("_", " ")
        if type_label:
            header.append(type_label)
        if r.get("description"):
            header.append(r["description"])
        if r.get("comedy_chemistry") is not None:
            header.append(f"comedy chemistry {r['comedy_chemistry']}/10")
        if header:
            lines.append("- " + " — ".join(header))

        for direction in r.get("directions") or []:
            from_name = direction.get("from_character_name") or "one"
            to_name = direction.get("to_character_name") or "the other"
            # affection and trust are independent (e.g. bickering siblings
            # can be low-trust but high-affection) — surface both when set
            # rather than assuming one implies the other.
            dynamics = []
            if direction.get("affection_level") is not None:
                dynamics.append(f"affection {direction['affection_level']}/10")
            if direction.get("trust_level") is not None:
                dynamics.append(f"trust {direction['trust_level']}/10")
            if direction.get("conflict_level") is not None:
                dynamics.append(f"conflict {direction['conflict_level']}/10")
            dyn_str = f" ({', '.join(dynamics)})" if dynamics else ""
            persp = f' — {from_name} thinks: "{direction["perspective_description"]}"' if direction.get("perspective_description") else ""
            if dyn_str or persp:
                lines.append(f"  · {from_name} toward {to_name}{dyn_str}{persp}")
            if direction.get("behavior_rules"):
                lines.append(f"    {from_name}'s rules toward {to_name}: " + "; ".join(direction["behavior_rules"]))

        # Recent history, oldest-of-the-recent-batch first so it reads as a
        # timeline rather than newest-first — the events themselves arrive
        # newest-first from the resolver (for UI display), reversed here
        # only for this narrative rendering.
        events = r.get("recent_events") or []
        if events:
            for e in reversed(events):
                if e.get("description"):
                    lines.append(f"  · (recently) {e['description']}")
    if not lines:
        return ""
    return (
        "\nEstablished relationship between these characters (each character's feelings/behavior toward "
        "the other may differ — keep both directions consistent, don't contradict either one; recent "
        "history shapes how they'd act now):\n" + "\n".join(lines) + "\n"
    )


def _build_prompt_from_context(source_type: str, context: str, variants: list, tone: str,
                                num_shots: int, target_duration_seconds: int,
                                character_personalities: Optional[dict] = None,
                                relationships: Optional[list] = None,
                                memories: Optional[list] = None,
                                cultures: Optional[list] = None,
                                performance_context: Optional[str] = None,
                                critique_feedback: Optional[str] = None,
                                previous_draft: Optional[dict] = None,
                                planned_scenes: Optional[list] = None) -> str:
    cast_line = _cast_line(variants, source_type, character_personalities)
    relationship_line = _relationship_context(relationships)
    memory_line = _memory_context(memories)
    culture_line = _culture_context(cultures)
    performance_line = performance_context or ""
    # When plan_scenes() has already locked the story's physical locations
    # (see that function's docstring), hand them back here as a fixed list
    # to pick from — every shot's own "location"/"scene_index" instructions
    # below branch on whether this is set. Absent for any caller that
    # hasn't been updated to plan scenes first, or chose not to — the
    # original single free-form "setting" behavior is unchanged then.
    if planned_scenes:
        scene_lines = "\n".join(
            f"  scene_index {s['scene_index']}: {s['description']}" for s in planned_scenes
        )
        planned_scenes_block = (
            "\nPLANNED LOCATIONS — this story takes place across EXACTLY these locations, already "
            f"locked, in this order:\n{scene_lines}\n"
        )
        location_field_instructions = """- "location" and "scene_index" together say WHERE this shot happens — both required, and they
  must agree: "location" is copied EXACTLY, word for word, from one of the PLANNED LOCATIONS
  above (never paraphrased, shortened, or invented), and "scene_index" is that location's own
  scene_index number. This whole script is rendered as ONE continuous video generation with no
  automatic scene changes between shots — a location change happens ONLY when scene_index
  itself changes from the previous shot's. Pick whichever planned location this specific shot's
  story beat actually belongs to; nothing says shots have to move through the list in order, but
  most scripts naturally will."""
        setting_field_instructions = (
            '- "setting" is a ONE-SENTENCE overall summary tying the PLANNED LOCATIONS above '
            "together (e.g. \"A story moving between a rural Indian kitchen and a bustling New "
            'York office."). The locations themselves already carry the real detail — this is '
            "just the throughline, not another full environment description."
        )
        scene_index_key = ", scene_index (int)"
    else:
        planned_scenes_block = ""
        location_field_instructions = """- "location" is the CONCRETE PHYSICAL PLACE this shot happens in (max ~25 words) — distinct from
  "setting" below (the one overall world the whole skit is framed in) and from "visual" (what's
  staged inside this place). This whole script is rendered as ONE continuous video generation
  with no automatic scene changes between shots — a location change happens ONLY if this field
  spells it out. Two rules, no exceptions:
  1. A shot in the SAME place as the previous shot repeats that previous shot's "location" text
     VERBATIM, word for word. Do not paraphrase or shorten it — a reworded repeat reads as a
     new place.
  2. A shot in a DIFFERENT place writes the new place out in full, naming architecture,
     materials and what's visible in the background, at the same concreteness as "setting"
     below (e.g. "A cramped Munich Standesamt office: grey filing cabinets, a queue-ticket
     dispenser, a laminated regulations poster on the wall" — not "a different office").
  Shot 1 always writes its location in full (there is no previous shot to match). If every
  character in this script is naturally tied to a different real place (e.g. each represents a
  different country), that is a reason to actually move the camera there shot by shot, not a
  reason to leave everyone standing together in one generic room for the whole video."""
        setting_field_instructions = """- "setting" is the WORLD this skit physically takes place in (max ~45 words), and it is the
  single biggest lever on whether the video feels immersive or bland. Put the characters
  INSIDE the subject matter rather than in a neutral room talking about it. If the trend is a
  game, a place, a film, a sport or a platform, stage the scene in that world and name its
  concrete visual signatures.
  Good — a Minecraft trend: "Inside a Minecraft world: blocky cubic terrain, a grass-block
  cliff, floating dirt islands, flickering torches on stone walls, pixelated sunset sky,
  low-poly trees casting hard square shadows."
  Bad — the same trend: "A living room where they talk about Minecraft." That wastes the
  premise and produces exactly the bland footage this field exists to prevent.
  Name materials, architecture, weather, time of day and era. Describe the empty set only —
  no characters, no actions, no dialogue.
  If the subject is a real-world SKY/LIGHT phenomenon (an eclipse, a sunset, an aurora, a meteor
  shower, a storm rolling in) the setting MUST be grounded at ground level outdoors with open sky
  actually visible — a field, a rooftop, a street, a beach — starting from ordinary daytime light,
  never a night backdrop, a space station, or anywhere already dim/starlit. Confirmed live
  2026-09-07: an eclipse script staged itself on a "futuristic space observatory" deck with a
  permanently starry sky in frame from shot 1 — there was no bright baseline left for anything to
  visibly darken FROM, so even a correctly-written darkening "lighting" field on the totality
  shot would have nothing to contrast against. The phenomenon's visual payoff depends on the
  viewer seeing the light actually change, which requires starting somewhere it can change from."""
        scene_index_key = ""
    # Showing the model the ACTUAL previous draft (not just abstract
    # feedback text) is what makes this a targeted revision instead of a
    # fresh rewrite — confirmed live: without the previous draft's real
    # content to anchor to, the model had nothing to "keep" and would
    # regenerate a whole new take on the premise, drifting to a different
    # storyline/scenario even when the critic only flagged one shot.
    if critique_feedback and previous_draft:
        critique_line = f"""
REVISION MODE — you are revising the EXISTING draft below, not writing a new story from
scratch. Keep the same characters, premise, story beats, and shots that are already working.
Make ONLY the minimal, targeted change needed to fix what the critic flagged below — do not
rewrite the whole scene, do not change the storyline or invent a different scenario. If the
critic pointed at one specific shot or line, revise JUST that shot; leave every other shot as
close to the original wording as possible.

PREVIOUS DRAFT:
{_format_script_for_prompt(previous_draft)}

CRITIC'S FEEDBACK ON THE DRAFT ABOVE: "{critique_feedback}"

Output the REVISED version of this exact script, addressing only what the critic flagged.
"""
    elif critique_feedback:
        # previous_draft missing (e.g. an old script row with no shots
        # stored) — fall back to feedback-only, same as before, better
        # than nothing but without the anchor a full rewrite is more likely.
        critique_line = (
            f"\nA critic reviewed an earlier draft of this exact premise and said: \"{critique_feedback}\" "
            "— address that specifically.\n"
        )
    else:
        critique_line = ""
    speaker_field = (
        '\n- "speaker_name" is the exact name of which listed character is acting/speaking in '
        "that shot (required when more than one character is listed; omit or null otherwise)."
        if len(variants) > 1 else ""
    )
    speaker_key = ", speaker_name (string or null)" if len(variants) > 1 else ""

    # An informative tone rewrites the writer's whole job: the goal is that
    # the viewer understands something afterwards, so "escalate the absurdity"
    # is actively wrong direction. Only the craft guidance and the worked
    # example swap — the cast, culture, camera and schema rules are the same
    # either way, and duplicating them would let the two drift apart.
    informative = is_informative_tone(tone)
    if informative:
        role_line = (
            "You are a scriptwriter for short character-based EXPLAINER videos for social "
            "video, grounded in the {source} below. The tone must be: {tone}.\n\n"
            "Your goal is that the viewer UNDERSTANDS the subject by the end. The characters "
            "are the teachers — their personalities make it engaging, but the explanation is "
            "the point, not the jokes."
        ).format(source=source_type, tone=tone)
        length_clause = "if it better serves the explanation"
        # Restrained on purpose: the comedy rule below demands an "exaggerated
        # physical beat", which in a science explainer produced the presenter
        # tripping over and dropping books between facts.
        action_rule = """describes what the character is physically doing, kept RESTRAINED (max ~12
  words) — they are narrating a phenomenon, not performing. A presenter gestures toward what
  they are explaining; they do not trip, drop things, flail or do slapstick. No physical
  comedy. Null on a "subject" shot."""
        craft_block = f"""Teaching craft — what separates a real explainer from vague content that sounds
informative but teaches nothing:
- ONE clear takeaway. Decide the single thing the viewer should be able to repeat afterwards,
  and build every shot toward it. An explainer that covers five things teaches none of them.
- CONCRETE over abstract. Never write the vague version ("AI is changing everything") — write
  the specific, checkable version with real numbers, names and mechanisms ("this model reads
  your last 50 messages, so it answers in your own phrasing").
- BUILD, don't list. Each shot should depend on the one before it: state the problem, then the
  mechanism, then the consequence. A sequence of unconnected facts is a list, not an explainer.
- ANALOGY for the hard part. The one genuinely difficult idea gets a physical, visual
  comparison the viewer already understands — that is what makes it stick.
- Use the cast to carry the structure: one character can hold the naive question the viewer is
  actually thinking, another the answer. Their personalities and cultures stay intact — a
  character who is blunt explains bluntly.
  REQUIRED when 2+ characters are cast: every one of them must be the speaker of at least one
  shot — a real question, reaction, or beat of their own, not just standing named in another
  character's blocking the whole time. Confirmed live 2026-09-07: a 3-character cast (Zara,
  Blix, Captain Nova) produced a script where Zara narrated the entire thing solo and the other
  two never spoke a single line — that defeats the point of casting them, and it also means the
  render has no real reason to ever anchor their identity. Give the second/third character a
  genuine question, a wrong guess Zara corrects, or a reaction beat with their own dialogue — not
  silent presence.
- Accuracy is a hard requirement. Do not invent statistics, studies or quotes. If you don't
  know a real number, describe the mechanism instead of fabricating a figure.
- SHOW THE PHENOMENON, not the presenter. The viewer came for the black hole, not for the
  person describing it. The MAJORITY of shots must be shot_focus "subject" — the thing
  itself, at real scale, filling the frame — with the character's voice carried over them as
  voiceover. Cut to the character only where seeing a face genuinely adds something: a
  reaction to a startling fact, or a moment of direct address. A script where every shot is
  the presenter holding a prop has failed, however good the words are.
  When the subject is a PROCESS that unfolds over time (an eclipse, a chemical reaction, a
  planet forming) rather than a static object, give it MULTIPLE subject shots, each ONE
  distinct stage of that process with its own specific subject_visual — not one shot's
  subject_visual trying to summarize the whole mechanism in a sentence. Confirmed live
  2026-09-07: a solar eclipse script gave the entire event exactly ONE subject shot at the
  very end, and everything before it was the presenter talking with the eclipse reduced to a
  screen behind her — the moon actually touching the sun's edge, the crescent narrowing,
  totality, the shadow racing across the ground were never their own moments at all. A
  multi-stage phenomenon with only one shot to its name is under-told regardless of how
  good that single subject_visual line reads.
- The character is the NARRATOR here, not the subject. Their personality lives in HOW they
  say things — word choice, delivery, what amazes them — not in physical business invented to
  give them something to do on camera.

Concrete example of the gap between a WEAK draft and what you should actually write —
same premise (explaining why AI models hallucinate), same length:

WEAK (reject this level — abstract, unconnected, teaches nothing):
  Shot 1, Zara: "AI is really powerful these days, but it has problems."
  Shot 2, Blix: "Yes, sometimes it gives wrong answers. That's called hallucination."
  Shot 3, Zara: "Interesting! So we should always check what it says."
  Shot 4: They nod thoughtfully.

STRONG (this is the bar):
  Shot 1, Zara (visual: holding a phone showing a confident, completely fake book citation;
  delivery: Baffled): "It just invented a book. Title, author, page number — the whole thing.
  Why does it LIE so confidently?"
  Shot 2, Blix (visual: at a whiteboard, drawing a sentence with the last word missing;
  delivery: Calm & Precise): "It isn't lying. It was never storing facts — it only ever learned
  to predict the next most likely word."
  Shot 3, Blix (visual: fills the blank with a plausible but wrong word, circles it;
  delivery: Building): "A fake citation LOOKS exactly like a real one. Same shape, same
  rhythm. So the most likely next word is a citation that doesn't exist."
  Shot 4, Zara (visual: lowers the phone, the realisation landing; delivery: Dawning): "So it's
  not recalling. It's autocompleting — and a confident wrong answer scores the same as a right
  one."

The difference: the strong version names ONE mechanism (next-word prediction), gives it a
visual the viewer can hold (the fill-in-the-blank on the whiteboard), and each shot depends on
the shot before it. The viewer can repeat the explanation afterwards. Match THIS level of
concreteness and structure on every shot.

THE EXAMPLE ABOVE IS A DEMONSTRATION OF CRAFT LEVEL ONLY, about ONE specific subject
(hallucination). It is not a template — do not reuse its subject, its mechanism (next-word
prediction), its whiteboard visual, its character names, or any of its lines for a script about
a different subject. Invent the actual mechanism, visual and specifics from the real subject
given below."""
    else:
        role_line = (
            "You are a scriptwriter for short character-based comedy skits for "
            f"social video, grounded in the {source_type} below. The tone must be: {tone}."
        )
        length_clause = "if it better serves the joke"
        action_rule = """describes the character's specific physical performance/movement in that
  shot (max ~15 words) — a concrete, exaggerated physical beat (e.g. "sweating, dancing
  manically" or "aggressively taps a stopwatch"), not a generic verb like "gestures" or
  "reacts." """
        craft_block = """Comedy craft — the single biggest thing separating a flat skit from a genuinely funny one:
- SPECIFICITY over generality. Never write a generic statement a real person might mildly
  say ("we celebrate with a big feast") — write the hyper-specific, concrete version instead
  (named props, exact numbers, absurd particulars: "a 500-person feast, 4 days of Bollywood
  dancing, and 12 aunties fighting over who holds him first"). If a line could apply to any
  character in any skit, rewrite it until it could only be THIS character.
- ESCALATE, don't parallel. Each character's beat should top the one before it, not just add
  a same-size data point next to it — the skit should feel like it's building to something,
  not listing options.
- COMMIT to the bit. Push each character's reaction to its absurd logical extreme rather than
  a safe, believable, "wholesome" version of it — even skits toned "wholesome" or "sad" should
  still be built from vivid, specific, committed beats rather than generic ones.
- Use the cast's personality/culture/relationship context above aggressively, not just as
  flavor text — a character with an established trait should take that trait to a comedic
  extreme, not just gently reference it.

Concrete example of the gap between a WEAK first draft and what you should actually write —
same premise (three friends comparing how their cultures react to a newborn), same length:

WEAK (reject this level — safe, generic, no escalation, mild anticlimax):
  Shot 1, Kumar: "In my culture, we celebrate with a big feast and loud music!"
  Shot 2, Aisha: "And in mine, we gather the community for blessings and prayers."
  Shot 3, Hans: "In my culture, we just... sleep. A lot."
  Shot 4: They laugh.
  Shot 5, Aisha: "Well, every culture has its own way, doesn't it?"

STRONG (this is the bar):
  Shot 1, Kumar (visual: wildly throwing confetti, holding a massive drum, manic energy;
  delivery: Loud & Hyped): "Bro! In my culture, a baby means a 500-person feast, 4 days of
  non-stop Bollywood dancing, and 12 aunties fighting over who holds him first!"
  Shot 2, Aisha (visual: pushes the drum away, waving a jug of sacred oil and a family tree
  scroll; delivery: Intense): "That's nothing! We chant blessings village-wide, sacrifice a
  goat, and give the baby seven names to confuse evil spirits!"
  Shot 3, Hans (visual: high-visibility safety vest, digital stopwatch, 400-page binder;
  delivery: Robotic/Deadpan): "In Germany the child is registered at the Standesamt for a tax
  ID immediately. Quiet hours are 22:00-06:00. Crying during those hours is an administrative
  offense."
  Shot 4: Music record-scratches out. Kumar and Aisha stare in horrified silence.
  Shot 5, Hans (visual: flips a clipboard page, ignoring their horror; delivery: efficient):
  "Also his recycling training begins at month three. Ordnung muss sein."

The difference isn't just wording — the strong version has real numbers (500-person, 4 days,
12 aunties, 7 names), real props (drum, confetti, sacred oil, scroll, safety vest, binder),
each beat is bigger/weirder than the last, and Hans's bureaucratic deadpan is pushed to a
genuinely absurd extreme instead of a throwaway "we sleep" aside. Match THIS level of
specificity and commitment, not the weak version, on every shot you write — regardless of
premise.

THE EXAMPLE ABOVE IS A DEMONSTRATION OF CRAFT LEVEL ONLY. It is not a template and must not be
reused. Confirmed live 2026-09-02: a script for an unrelated premise (comparing how different
countries handle a new student's first day) reproduced this exact example almost verbatim —
same feast/dancing/aunties beat, same safety-vest/stopwatch/binder/Standesamt beat down to
"Ordnung muss sein" — with only the noun "baby" swapped for "new student." That is not writing a
new scene, it is copying this one. Your script must not reuse this example's premise (a newborn
baby), its countries, its specific props (drum, confetti, sacred oil, scroll, safety vest,
binder, stopwatch), its exact numbers (500, 4 days, 12, 7), its phrases ("Ordnung muss sein" or
any other line here), or its character-to-culture mapping. If your draft shares any of those
specifics with the example, you have copied it — discard it and invent a genuinely new premise,
escalation and set of specifics from the persona/trend context actually given below."""

    return f"""{role_line}

{context}
{planned_scenes_block}
{cast_line}
{relationship_line}
{memory_line}
{culture_line}
{performance_line}
{critique_line}
Aim for around {num_shots} shots totaling about {target_duration_seconds} seconds, though you
may adjust within the hard limits below {length_clause}.

{craft_block}

Camera — the writer also directs the shot, don't leave this to chance: vary shot_type
meaningfully across the sequence rather than defaulting to the same medium/talking-head shot
every time — use establishing/wide shots to open or reset a scene, closeup/extreme_closeup for
a reaction or comedic beat, two_shot/over_shoulder for a dialogue exchange, insert for a prop
close-up (e.g. that stopwatch), reveal for a punchline. Not every shot needs camera_movement
(static is a real, correct choice), but push_in on an escalating line or whip_pan into a reveal
reads as far more intentional than leaving every shot on the same static medium framing.

Dialogue rhythm — for a 2+ character script, do NOT default to strict back-and-forth turn-taking
(A speaks, B speaks, A speaks, B speaks...) for the whole runtime. That's a ping-pong match, not
a scene — confirmed live 2026-09-07: a 9-shot Brian/Hans script alternated speaker on literally
every single shot, with nearly the same "X left, Y right, both facing camera" two-shot blocking
repeated each time, only the dialogue changing. A real scene has uneven rhythm: let a character
carry TWO OR THREE shots in a row to build one whole beat (a rising bit, a rant, a demonstration)
before cutting away, rather than handing the other character a reflexive one-line reply every
single time. Vary who gets the longer run of screen time between beats — one character dominates
the opening, another owns the turn, not a metronome. And vary blocking BETWEEN shots the way
you'd vary shot_type — position, distance, who's near what — not the same symmetric two-shot
held for the whole script with only the line changing.

Character presence — how a character is framed changes across their own coverage, it isn't
fixed for the whole script:
- A character's FIRST shot in a given location (their first appearance there — not necessarily
  shot 1 overall) must be an unambiguous, close/solo introduction beat: them alone or with at
  most one other character, clearly framed, not buried in a crowd. The render anchors identity
  on exactly this kind of shot — a character who is never given one never gets rendered
  accurately.
- Once a character has had that introduction in a location, their LATER shots there are free to
  place them smaller, off-center, part of a busier composition — they don't need to repeat a
  centered close-up every time they're on screen again.
- Dialogue delivery is a per-shot DIRECTORIAL CHOICE, not a fixed pattern to default into: a line
  can be delivered face to face between two characters in frame together, as voiceover while the
  speaker is shown small within a wider shot (or not shown at all, on a "subject" shot), or as a
  deliberate centered close-up for emphasis at a beat that earns it. Use whichever actually serves
  that specific moment — don't let the whole script settle into only one of these.

Requirements:
- Between {MIN_SHOTS} and {MAX_SHOTS} shots. shot_number must be 1, 2, 3... with no gaps.
- Each shot's duration_seconds is a whole number >= 1. The SUM of all shots'
  duration_seconds must be between {MIN_TOTAL_SECONDS} and {MAX_TOTAL_SECONDS} (hard limits).
{location_field_instructions}
- "visual" describes the staging: props, environment, positioning, what's physically in frame
  (max ~35 words). Name specific OBJECTS and MATERIALS, not categories — "a chipped enamel
  teapot on scratched oak, a half-eaten plate of jalebi, coats piled on the chair back" rather
  than "kitchen items". Concrete props are what make a shot read as a real place on screen.
- "lighting" describes the light in this shot with a DIRECTION and a quality (max ~15 words) —
  e.g. "warm lamp from frame left, cold blue window light from the right" or "single overhead
  fluorescent, hard shadows". Keep it consistent between shots in the same location unless the
  story changes it; consistent light is what makes separate shots feel like one continuous scene
  rather than unrelated clips.
  EXCEPTION — if the subject itself changes the light (an eclipse progressing, a sunset, a storm
  rolling in, a power outage, fireworks, an explosion), the lighting field MUST change shot to
  shot to track it: describe the actual light getting dimmer/warmer/redder, shadows softening or
  vanishing, colors muting. Confirmed live 2026-09-07: an eclipse script wrote "the moon
  completely covers the sun, leaving only a glowing corona" as the visual for its final shot but
  reused the exact same "Natural sunlight from above, with no other light sources" lighting line
  from shot 1 for every shot including that one — the rendered video never dimmed at all because
  nothing in the prompt ever asked it to. Writing the phenomenon into "visual" is not enough by
  itself; "lighting" has to carry the actual light-level change or the render has no reason to
  show it.
  The change must land on the SAME shot whose "visual"/"subject_visual" describes the peak
  effect, not a shot after it. Confirmed live 2026-09-07 again on the retry: the shot literally
  describing "the moon completely covers the sun, leaving only a glowing corona" (totality) still
  kept the bright, unchanged lighting line — only the NEXT shot's lighting was updated to
  "dimmer". That shot renders bright regardless of what the following shot says; the darkening
  has to be written into that shot's own lighting field, exactly in step with what its own visual
  is depicting, not deferred to whatever comes after it.
- "blocking" says WHERE each character PRESENT IN THIS SHOT is in the frame and what they
  physically hold (max ~20 words). Only name characters who are actually in this shot — for a
  multi-character script, most shots should be about ONE character alone or two at most, not
  the full cast. e.g. a shot that is Hans's moment is "Hans centre with the laptop", not "Hans
  centre with the laptop, Kumar left holding a mug, Wen right with a book" — do not pad blocking
  with cast members who have no reason to be in that shot. Defaulting to the whole cast lined up
  in every shot (one stepping forward to speak while the others stand and wait) is the single
  most common failure of multi-character blocking — it reads as a static group photo, not a
  scene, and makes it harder to tell who is actually speaking. Cut to a character's own shot
  instead of keeping everyone on screen throughout.
  HARD RULE, not just a pacing preference: NEVER name 2+ cast members together as equally
  present in one shot's blocking (a "gathered together", "all three looking up", "the whole
  crew" closing beat is the classic place this happens). The render anchors each segment on
  exactly ONE character's real photo — every OTHER named character in that shot has no photo
  reference at all, and confirmed live 2026-09-07 on two separate scripts, the render does not
  draw them as themselves or even as generic strangers — it duplicates the one anchored face to
  fill the extra people, so "Zara, Blix, and Captain Nova standing together" came back as two
  visibly identical Zaras. If the story wants a full-cast ending, cut rapidly between separate
  single-character shots (each its own beat, each anchored on its own speaker) rather than
  writing one shared shot that claims multiple named identities at once — a name only belongs in
  blocking when they are that shot's own anchored focus.
  Only the named cast members supplied to you have a real photo the render is anchored to. If a
  shot needs other people on screen (a crowd, classmates, a teacher), describe them ONLY as
  generic, unnamed background extras ("a cluster of classmates in the background") — never give
  a non-cast person a name, a distinct description, or dialogue. An invented named character has
  no photo to be drawn from and the render has nothing to anchor them to.
- "action" {action_rule}
- "shot_focus" is WHAT THE CAMERA IS ON, one of exactly: {SHOT_FOCUS_TYPES}.
    "character" — the character performs on camera. A talking head.
    "subject"   — the camera is on the THING being talked about, and NO character is visible
                  in frame at all. The black hole itself, the game world, the object.
    "both"      — the character is in frame WITH the subject (e.g. dwarfed by it, pointing
                  at it, reaching into it).
  Do NOT make every shot "character". A sequence of talking heads in front of a background
  is the single most common failure of this format. Open on the subject wherever the premise
  has one, cut to the character to react or explain, and return to the subject to close.
  At least one shot in every script of 3+ shots must be "subject" or "both".
  If a "both" shot has dialogue, "blocking"/"action" must keep the speaker's face toward
  camera — glancing toward the subject or gesturing at it is fine, but do NOT write them as
  fully turned away or head craned up/off staring at the subject while they're also supposed
  to be delivering the line. Confirmed live 2026-09-07: a shot blocked as "looking up at the
  sky, adjusting binoculars" while carrying that character's only line rendered as her turning
  away from camera in silence — the physical action of looking away won over the dialogue, so
  the line was never delivered on screen at all. A character can't be shown speaking to camera
  and looking away from it in the same shot; write the action so both can actually happen.
- "subject_visual" describes what fills the frame when shot_focus is "subject" or "both"
  (max ~30 words) — the thing itself, cinematically, with scale and motion: "a supermassive
  black hole filling frame, orange accretion disk churning, starlight bending around the
  event horizon". Null only when shot_focus is "character".
  SHOW IT AT REAL SCALE. Never substitute a desk model, a toy, a poster, a diagram, a
  projector or a screen for the phenomenon itself — a black hole is the actual black hole
  in space, filling the frame, not a glowing prop on a classroom table. A miniature on a
  table is the same failure as staging a Minecraft trend in a living room.
- "voiceover" is true when the character's dialogue is HEARD OVER the shot while they are not
  on screen — the standard way to open on the subject and still have someone narrating it.
  Only meaningful when shot_focus is "subject"; false otherwise.
- "expression" is one of exactly these values, or null if not relevant: {EXPRESSION_NAMES}.
  Null for a "subject" shot, where no face is on screen.
- "dialogue" is what the character says out loud in that shot, or null for a
  silent/reaction-only beat. Give it real voice — specific, escalating, in-character, not a
  generic informative sentence.
  HARD PACING LIMIT: a line must be sayable, unrushed, inside its own shot. Budget
  {SPEECH_WORDS_PER_SECOND} words per second of duration_seconds — a 3-second shot takes about
  7 words, a 4-second shot about 10. Count the words. Going over does NOT extend the shot: the
  voice is sped up to fit and the delivery sounds rushed and unnatural. If a line needs more
  words, give the shot more seconds or split it across two shots.
- "dialogue_delivery" is a short (2-4 word) delivery-style tag for how the line is performed
  (e.g. "Loud & Hyped", "Deadpan / Robotic", "Whispered, intense") — null when dialogue is null.
- "shot_type" must be one of exactly these values: {SHOT_TYPES}.
- "camera_movement" must be one of exactly these values, or null for a static shot: {CAMERA_MOVEMENTS}.
- hook_line is a punchy, stand-alone opening line/on-screen text summarizing the skit (max 15 words).
{setting_field_instructions}{speaker_field}

Return ONLY valid JSON with exactly these keys:
- hook_line: string
- setting: string
- shots: array of objects, each with exactly: shot_number (int), duration_seconds (int),
  location (string), visual (string), lighting (string), blocking (string), action (string),
  shot_focus (string), subject_visual (string or null), voiceover (boolean),
  expression (string or null), dialogue (string or null),
  dialogue_delivery (string or null), shot_type (string), camera_movement (string or null),
  people (string: "none", or "distant" or "reference" only where the PEOPLE rule in the context allows it; otherwise always "none"),
  year (integer or null: the calendar year this shot depicts, BC as a negative number, when the PERIOD GUIDE in the context asks for it; otherwise null){scene_index_key}{speaker_key}

Return ONLY the JSON object, no other text."""


def _build_prompt(persona_or_cluster, variants: list, tone: str, num_shots: int, target_duration_seconds: int,
                   character_personalities: Optional[dict] = None, relationships: Optional[list] = None,
                   memories: Optional[list] = None, cultures: Optional[list] = None,
                   performance_context: Optional[str] = None, critique_feedback: Optional[str] = None,
                   previous_draft: Optional[dict] = None, planned_scenes: Optional[list] = None) -> str:
    source_type, context = _source_type_and_context(persona_or_cluster)
    return _build_prompt_from_context(source_type, context, variants, tone, num_shots, target_duration_seconds,
                                       character_personalities, relationships, memories, cultures, performance_context,
                                       critique_feedback, previous_draft, planned_scenes)


def _assign_speakers(shots: list, variants: list) -> list:
    """Maps each shot's LLM-produced "speaker_name" to a real variant's id
    as "speaker_variant_id" (matched case-insensitively against the
    supplied variants; no match or a single-variant script leaves it unset,
    defaulting to the primary/first variant downstream). "speaker_name" is
    dropped from the returned shots — it's an LLM-facing field only, the
    persisted/returned shape uses speaker_variant_id (see ToonScript's
    shots column docstring)."""
    if not variants:
        return shots
    by_name = {v.name.strip().lower(): str(v.id) for v in variants}
    result = []
    for shot in shots:
        shot = dict(shot)
        speaker_name = (shot.pop("speaker_name", None) or "").strip().lower()
        variant_id = by_name.get(speaker_name)
        if variant_id:
            shot["speaker_variant_id"] = variant_id
        result.append(shot)
    return result


def label_speakers(shots: list, variants: list) -> list:
    """Inverse of _assign_speakers: puts "speaker_name" back on each shot.

    Persisted shots only carry speaker_variant_id, so a stored script handed
    straight back to the LLM as a revision draft reads as dialogue nobody is
    attributed to — and the model then re-assigns lines to whichever
    character it likes. That is the same failure as a shot rendering the
    wrong speaker, just introduced one step earlier, so revision drafts get
    the names restored before the prompt is built.
    """
    if not variants:
        return shots
    by_id = {str(v.id): v.name for v in variants}
    result = []
    for shot in shots or []:
        shot = dict(shot)
        name = by_id.get(str(shot.get("speaker_variant_id") or ""))
        if name:
            shot["speaker_name"] = name
        result.append(shot)
    return result


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _call_llm_json(prompt: str, temperature: float = 0.7, max_tokens: int = 900) -> dict:
    """Shared Qwen-max (primary) / Claude Haiku (fallback) JSON-mode call —
    every LLM call in this module funnels through here (script writing AND
    the comedy judge below). Raises ToonScriptGenerationError on any
    failure (bad JSON, network, auth) rather than letting a raw SDK
    exception leak past this module's boundary."""
    try:
        if os.getenv("QWEN_API_KEY"):
            qwen = _get_qwen_client()
            response = qwen.chat.completions.create(
                model="qwen-max",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            raw = response.choices[0].message.content
        else:
            client = _get_claude_client()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
        return _parse(raw)
    except json.JSONDecodeError as exc:
        raise ToonScriptGenerationError(f"Model returned invalid JSON: {exc}") from exc
    except Exception as exc:
        raise ToonScriptGenerationError(str(exc)) from exc


def derive_scene_setting(script) -> dict:
    """Derives a real PHYSICAL SETTING for a script, for use as a
    ToonBackground's name/description/country.

    Why this exists: _script_scene_description() in the router falls back to
    concatenating each shot's `action` line when a script has no
    scene_direction (which is every AI-generated, shot-structured script).
    Those lines describe what PEOPLE DO, not where they are — its own
    comment already flagged this ("John looks around confused... Kumar
    shakes his head... describe people's behavior, not the venue").
    Confirmed live 2026-09-01 against real rows: every Location in the DB
    had a comedic premise as its `name` ("Wikipedia searches for King
    Harald V of Norway go hilariously wrong.") and a run-on list of
    character actions as its `description`, with country always NULL. That
    text then feeds the video prompt as "Set in <joke>: <list of actions>",
    which is incoherent scene direction on every single generation.

    Returns {"name", "description", "country"} — a short location name, a
    visual description of the PLACE (no characters, no plot), and a country
    when the script implies one (else None). Raises
    ToonScriptGenerationError on LLM failure, same as every other call in
    this module; callers decide whether to fall back."""
    source_parts = []
    if getattr(script, "hook_line", None):
        source_parts.append(f"Hook: {script.hook_line}")
    if getattr(script, "scene_direction", None):
        source_parts.append(f"Scene direction: {script.scene_direction}")
    for i, shot in enumerate(getattr(script, "shots", None) or [], start=1):
        bits = [shot.get(k, "") for k in ("visual", "action", "dialogue")]
        line = " / ".join(b.strip() for b in bits if b and b.strip())
        if line:
            source_parts.append(f"Shot {i}: {line}")
    source = "\n".join(source_parts).strip()
    if not source:
        raise ToonScriptGenerationError("Script has no hook, scene direction or shots to derive a setting from")

    prompt = (
        "You are a production designer. Read the script below and identify the single physical "
        "LOCATION the scene takes place in.\n\n"
        f"{source}\n\n"
        "Return JSON with exactly these keys:\n"
        '  "name": a short location name, 2-5 words, e.g. "Cramped train carriage" or '
        '"Indian home kitchen". This is a PLACE, never a joke, plot summary or episode title.\n'
        '  "description": 1-2 sentences describing only what the place LOOKS like — architecture, '
        "furniture, props, lighting, time of day, mood. Describe the empty set: no characters, no "
        "people, no actions, no dialogue.\n"
        '  "country": the country the location is in if the script implies one, else null. Infer it '
        "from cultural cues (names, food, language, landmarks, subject matter), not just from an "
        "explicit statement.\n\n"
        "IMPORTANT — preserve cultural specificity. This is a culturally-grounded comedy product: if "
        "the script implies a particular culture or region, the location must reflect it concretely "
        "(architecture, furnishings, textiles, cookware, signage, streetscape). Never flatten a "
        'culturally specific setting into a generic or "modern/futuristic" one.\n'
        "If the script never establishes a location, infer the most plausible ordinary one from context."
    )
    parsed = _call_llm_json(prompt, temperature=0.4, max_tokens=400)
    name = (parsed.get("name") or "").strip()
    description = (parsed.get("description") or "").strip()
    if not name or not description:
        raise ToonScriptGenerationError(f"Setting derivation returned no usable name/description: {parsed}")
    country = parsed.get("country")
    country = country.strip() if isinstance(country, str) and country.strip() else None
    return {"name": name, "description": description, "country": country}


def plan_scenes(context: str, tone: str, variants: list, target_duration_seconds: int) -> list:
    """Decides, BEFORE any shot gets written, how many distinct physical
    locations this specific story needs (1 to MAX_PLANNED_SCENES — always
    theme-driven, never a fixed count) and writes each one as a fully
    exhaustive, locked environment description. The shot-writer prompt
    then hands these back as a fixed list to pick from per shot (see
    _build_prompt_from_context's planned_scenes param) instead of a shot
    inventing or drifting its own "location" text shot by shot.

    Added 2026-09-08 per an explicit rework request, after three narrower
    prompt-only fixes (camera-facing speakers, no naming 2+ cast in one
    shot's blocking, lighting tracking a phenomenon) still left every
    segment anchored on one flat, whole-script text description of "the
    setting" — which is why an eclipse script kept reading as a sunset:
    "the decision of how many scenes (dynamic backgrounds) will be
    necessary per toon will depend on the theme... if you want to make
    engaging videos you have to make the users travel" — so this must not
    hardcode a count, and a single-location story choosing exactly 1 scene
    is a correct, expected outcome, not an under-use of the feature.

    context/tone/variants: same shape as the shot-writer's own
    _build_prompt_from_context call (context is the persona/cluster/idea
    text already assembled by the caller). Returns
    [{"scene_index": int, "description": str}, ...] in story order. Raises
    ToonScriptGenerationError on LLM failure or an unusable response, same
    as every other call in this module."""
    cast_names = ", ".join(v.name for v in variants if getattr(v, "name", None)) or "the cast"

    prompt = (
        "You are a production designer planning the PHYSICAL LOCATIONS a short video will be "
        "shot in, before a single shot is written.\n\n"
        f"{context}\n\n"
        f"Tone: {tone}. Cast: {cast_names}. The whole story runs about "
        f"{target_duration_seconds} seconds total.\n\n"
        "Decide how many DISTINCT physical locations this specific story genuinely needs — "
        "driven by the story, not a fixed number. A scene that never leaves one room needs "
        "exactly 1 location; that is a correct answer, not a lesser one. A story that compares "
        "something across cultures, follows a journey, or has a clear before/after moment "
        "(arriving somewhere, a transformation, a phenomenon unfolding across a changing sky) "
        "should actually move the camera there — write as many locations as the story needs to "
        f"feel like it travels, up to {MAX_PLANNED_SCENES}. Do not pad the count with a location "
        "the story doesn't need, and do not force a story that wants to travel into one location "
        "just to keep this simple.\n\n"
        "For EACH location, write a FULLY exhaustive, locked description (60-100 words) — enough "
        "that nothing about the physical space itself is left for anyone downstream to invent or "
        "guess: architecture/terrain, materials, specific props already in the space, weather, "
        "time of day, and the quality and DIRECTION of the ambient light. Two different locations "
        "must read as visibly different places, not variations on the same room.\n\n"
        "If the subject is a real-world SKY/LIGHT phenomenon (an eclipse, a sunset, an aurora, a "
        "storm), its location must be grounded at ground level outdoors with open sky actually "
        "visible, starting from ordinary daytime light — never a space station, a night backdrop, "
        "or anywhere already dim. There has to be a bright baseline for the light to visibly "
        "change FROM.\n\n"
        "Return ONLY valid JSON with exactly one key:\n"
        "- scenes: array of objects, each with exactly: scene_index (int, starting at 0, in the "
        "order the story visits this location), description (string, the locked environment "
        "description above)\n\n"
        "Return ONLY the JSON object, no other text."
    )
    parsed = _call_llm_json(prompt, temperature=0.6, max_tokens=700)
    scenes = parsed.get("scenes") or []
    # scene_index is renumbered contiguously (0, 1, 2...) from whichever
    # scenes actually have usable text, NOT copied from the model's own
    # numbering — a dropped scene must not leave a gap, since this index is
    # what shots/backgrounds key off downstream (see plan_scenes' own
    # callers) and a gap there is a needless way to break that lookup.
    cleaned = []
    for scene in scenes[:MAX_PLANNED_SCENES]:
        description = (scene.get("description") or "").strip()
        if description:
            cleaned.append({"scene_index": len(cleaned), "description": description})
    if not cleaned:
        raise ToonScriptGenerationError(f"Scene planning returned no usable locations: {parsed}")
    return cleaned


def _call_llm_for_script(prompt: str, tone: str, variants: list, planned_scenes: Optional[list] = None) -> dict:
    parsed = _call_llm_json(prompt, temperature=0.7, max_tokens=900)
    # Pace before anything else reads the shots, so the stored duration is
    # always one the line actually fits into — see fit_shot_durations.
    shots = fit_shot_durations(parsed.get("shots") or [])
    total = sum(s.get("duration_seconds", 0) for s in shots) if shots else 0
    return {
        "hook_line": parsed.get("hook_line"),
        # The world the skit is staged in. Previously an AI-generated script
        # carried no setting at all — only hook_line/tone/shots — so unless
        # someone separately picked a Location, nothing ever told the video
        # model WHERE the scene happens. A Minecraft trend then rendered as
        # people in a neutral room, which is the "bland background" problem.
        "setting": parsed.get("setting"),
        "tone": tone,
        "shots": _assign_speakers(shots, variants),
        # The SUM of the paced shots, not the model's own figure — after
        # fit_shot_durations the two disagree, and the shots are the truth.
        # The stale figure is what a render would have been billed for.
        "total_duration_seconds": total or parsed.get("total_duration_seconds"),
        # [{"scene_index", "description"}, ...] from plan_scenes(), or None
        # when the caller didn't plan scenes — the router uses this to
        # generate one backdrop image per location and build ToonScript.
        # scene_backgrounds (see app/services/culturetoon_selfhosted_video.py
        # for the render-side half of this).
        "scenes": planned_scenes,
    }


def _format_script_for_prompt(script_result: dict) -> str:
    """Renders a {hook_line, shots} dict as readable text for an LLM
    prompt — shared by the judge prompt and the revision-mode prompt
    below, so both see the script in the exact same shape."""
    hook = script_result.get("hook_line") or ""
    shot_lines = []
    for s in script_result.get("shots") or []:
        parts = [f"Shot {s.get('shot_number')}"]
        if s.get("shot_type"):
            parts.append(f"[{s['shot_type']} shot" + (f", {s['camera_movement']}]" if s.get("camera_movement") else "]"))
        if s.get("speaker_name"):
            parts.append(f"Character: {s['speaker_name']}")
        if s.get("location"):
            parts.append(f"Location: {s['location']}")
        if s.get("visual"):
            parts.append(f"Visual: {s['visual']}")
        # Every craft field the generator can emit is rendered back here.
        # In revision mode this text IS the draft the model edits, so a
        # field missing from it reads as a field the draft never had — an
        # enrich would then silently drop the lighting and blocking of
        # every shot it wasn't asked to touch.
        if s.get("lighting"):
            parts.append(f"Lighting: {s['lighting']}")
        if s.get("blocking"):
            parts.append(f"Blocking: {s['blocking']}")
        if s.get("action"):
            parts.append(f"Action: {s['action']}")
        if s.get("expression"):
            parts.append(f"Expression: {s['expression']}")
        if s.get("dialogue"):
            delivery = f" ({s['dialogue_delivery']})" if s.get("dialogue_delivery") else ""
            parts.append(f'Dialogue{delivery}: "{s["dialogue"]}"')
        shot_lines.append(" | ".join(parts))
    # The world the whole scene plays in — same reason as the per-shot
    # fields: without it a revision re-invents the setting instead of
    # keeping the one already on the script.
    setting = (script_result.get("setting") or "").strip()
    setting_line = f"Setting: {setting}\n\n" if setting else ""
    return f"{setting_line}Hook: {hook}\n\n" + "\n".join(shot_lines)


# Per-tone judge rubrics: (critic framing, [criteria lines], passes_bar
# clause). Keyed by the exact TONE_OPTIONS string. A script's rubric must
# match what its writer prompt was actually asked for — the same reasoning
# that motivated the original informative/comedy split (an explainer judged
# by a comedy critic fails for not being funny, which is both wrong and
# unactionable) extends to every tone: a dramatic scene judged by the
# comedy rubric (reward absurd escalation) fails for not being ABSURD,
# which is exactly backwards for drama. Each tone gets criteria that
# reward what THAT tone is actually trying to do, not a reskin of comedy's.
_TONE_JUDGE_RUBRICS = {
    "educational": (
        "a blunt, strict editor",
        "educational",
        [
            "CLARITY: one clear, teachable takeaway a viewer could repeat or apply "
            "afterward, not five half-covered points.",
            "CONCRETENESS: real mechanisms, numbers and names, not abstract claims like "
            "\"AI is changing everything\".",
            "STRUCTURE: each shot builds toward that one takeaway, not a list of "
            "unconnected facts.",
            "ACCURACY: nothing invented. Penalise fabricated-sounding statistics, studies "
            "or quotes heavily, and say so in the feedback.",
        ],
        "true only if a viewer could actually repeat or apply the one teachable takeaway "
        "afterward",
        "too vague or unsupported and say what to replace it with, don't just say "
        "\"be clearer\"",
    ),
    "explainer": (
        "a blunt, strict editor",
        "explainer",
        [
            "MECHANISM: a genuine step-by-step account of HOW the thing actually works, "
            "not a surface description that skips the real mechanism.",
            "CLARITY: one clear through-line a viewer could repeat afterward, not several "
            "half-covered angles.",
            "STRUCTURE: each shot is a real step (cause, mechanism, consequence), not a "
            "list of loosely related facts.",
            "ACCURACY: nothing invented. Penalise fabricated-sounding statistics, studies "
            "or quotes heavily, and say so in the feedback.",
        ],
        "true only if it actually explains the mechanism a viewer could repeat, not just "
        "describes the topic",
        "skips the real mechanism or is unsupported, and say what to replace it with",
    ),
    "informative": (
        "a blunt, strict editor",
        "informative facts",
        [
            "RELEVANCE: facts that are genuinely interesting or non-obvious, not things "
            "most viewers already know.",
            "CONCRETENESS: specific numbers, names and examples, not vague general "
            "statements.",
            "COHERENCE: the facts connect into one throughline, not an unrelated grab-bag "
            "glued together.",
            "ACCURACY: nothing invented. Penalise fabricated-sounding statistics, studies "
            "or quotes heavily, and say so in the feedback.",
        ],
        "true only if the facts are genuinely non-obvious and connect into one throughline",
        "too obvious/generic or doesn't connect to the rest, and say what to replace it with",
    ),
    "inspirational": (
        "a blunt, strict editor",
        "inspirational",
        [
            "SPECIFICITY: grounded in a real, concrete story, fact or detail — not a "
            "generic platitude like \"believe in yourself\".",
            "EARNED UPLIFT: the uplift follows from something actually shown or explained "
            "in the scene, not just asserted.",
            "AUTHENTICITY: avoids empty motivational-poster language in favor of something "
            "that feels genuinely earned.",
        ],
        "true only if the uplift is earned by a specific, shown detail, not asserted",
        "reads as a generic platitude and say what specific detail would earn it instead",
    ),
    "funny": (
        "a blunt, strict comedy critic",
        "skit",
        [
            "SPECIFICITY: concrete props/numbers/particulars, not generic statements a real "
            "person might mildly say.",
            "ESCALATION: each beat tops the one before it, not a flat list of parallel/"
            "same-size beats.",
            "COMMITMENT: characters pushed to an absurd, committed extreme, not a safe/mild "
            "version.",
        ],
        "true only if genuinely funny and specific — most drafts should fail",
        "too generic/mild and say what direction to push it, don't just say \"make it funnier\"",
    ),
    "dramatic": (
        "a blunt, strict drama critic",
        "dramatic scene",
        [
            "STAKES: something a character genuinely stands to lose or gain, not a "
            "low-consequence situation dressed up as serious.",
            "TURN: the scene changes something — a realization, a decision, a reveal — rather "
            "than just restating the premise for its whole length.",
            "RESTRAINT: emotion is shown through specific action/dialogue, not announced "
            "outright (\"I'm so hurt\") or pushed into melodrama.",
        ],
        "true only if it earns real emotional weight through specifics, not asserted drama",
        "where it tells instead of shows, or where the stakes are too vague to land",
    ),
    "satiric": (
        "a blunt, strict satire editor",
        "satirical scene",
        [
            "TARGET: a specific, recognizable real-world behavior, type or institution being "
            "skewered, not a vague generic joke.",
            "EXAGGERATION WITH LOGIC: the absurdity follows the target's own internal logic "
            "pushed further, not random unrelated weirdness.",
            "POINT: a viewer could state exactly what's being mocked and why — it isn't just "
            "\"that was weird.\"",
        ],
        "true only if there's a real, nameable target and the exaggeration serves it",
        "where the target is too vague or the exaggeration doesn't track its own logic",
    ),
    "sad": (
        "a blunt, strict editor reviewing an emotional scene",
        "scene",
        [
            "SPECIFICITY: one concrete, particular detail of the loss (an unfinished small "
            "thing, a specific object) rather than a generic statement like \"she was sad\".",
            "EARNED: the emotional beat follows from what's actually shown in the scene, not "
            "just asserted by a character saying how they feel.",
            "RESTRAINT: lands without melodrama or on-the-nose narration explaining the "
            "feeling instead of showing it.",
        ],
        "true only if the emotion is earned through a specific, shown detail, not asserted",
        "where it tells the feeling instead of showing a concrete detail that earns it",
    ),
    "wholesome": (
        "a blunt, strict editor reviewing a warm/feel-good scene",
        "scene",
        [
            "SPECIFICITY: a concrete gesture or detail of care between these particular "
            "characters, not generic niceness that could belong to anyone.",
            "EARNED CONNECTION: grounded in what's already established about these "
            "characters' relationship/personalities, not interchangeable pleasantness.",
            "RESTRAINT: warm without curdling into saccharine or stopping to moralize about "
            "the lesson.",
        ],
        "true only if the warmth is specific to these characters, not generic niceness",
        "where the warmth is generic/interchangeable or tips into saccharine",
    ),
    "chaotic": (
        "a blunt, strict comedy critic reviewing a chaos-escalation scene",
        "scene",
        [
            "MOMENTUM: each beat makes things MORE out of control than the last, compounding "
            "rather than resetting to a new unrelated bit.",
            "CAUSALITY: the chaos follows some — however absurd — chain of cause and effect, "
            "not a string of random unconnected events.",
            "COMMITMENT: characters react to the escalating chaos with real, specific "
            "reactions, not just narration that chaos is happening.",
        ],
        "true only if the chaos genuinely compounds beat to beat with real causality",
        "where the escalation resets instead of compounding, or events don't causally connect",
    ),
    "deadpan": (
        "a blunt, strict comedy critic reviewing a deadpan scene",
        "scene",
        [
            "CONTRAST: the more absurd the situation, the flatter and more matter-of-fact the "
            "character's reaction/delivery — that gap IS the joke.",
            "SPECIFICITY: a concrete, particular detail stated plainly, not a generic \"that's "
            "weird\" reaction.",
            "RESTRAINT: no mugging, no exclamation points, no explaining the joke — flatness "
            "undercut by any of those fails the bit.",
        ],
        "true only if the flat delivery genuinely contrasts with real absurdity",
        "where the delivery breaks flat (mugging, exclamation, over-explaining) or the "
        "situation isn't absurd enough to need it",
    ),
}


def _build_judge_prompt(script_result: dict) -> str:
    script_text = _format_script_for_prompt(script_result)
    tone = (script_result.get("tone") or "").strip().lower()

    # Fall back to the "funny" rubric for any tone not in the table (should
    # only happen for a value outside TONE_OPTIONS, e.g. old data) — better
    # than crashing the judge over an unrecognized tone string.
    framing, noun, criteria, passes_clause, feedback_clause = _TONE_JUDGE_RUBRICS.get(
        tone, _TONE_JUDGE_RUBRICS["funny"]
    )
    criteria_block = "\n".join(f"- {line}" for line in criteria)
    return f"""You are {framing} reviewing a short {noun} script before it gets turned into
video. Score it honestly — most first drafts are too safe and should NOT pass; a passing score
should be rare, reserved for scripts that are genuinely specific and committed, not just "fine."

{script_text}

Score against these specific criteria (the exact bar the writer was given):
{criteria_block}

Return ONLY valid JSON with exactly these keys:
- comedy_score: integer 0-100 (scores against the criteria above, whatever this tone's actual
  goal is — not necessarily humour)
- passes_bar: boolean ({passes_clause})
- feedback: string, 1-3 sentences of SPECIFIC actionable critique — name the exact line that's
  {feedback_clause}

Return ONLY the JSON object, no other text."""


def judge_script_comedy(script_result: dict) -> dict:
    """Scores a freshly generated script against the same comedy-craft bar
    the writer prompt was given, via a SEPARATE LLM call — a fresh critic,
    not the same model grading its own output in the same turn. Mirrors
    app/services/culturetoon_qa.py::run_ai_judge_qa's existing post-video
    comedy scoring, just moved earlier (script-only, pre-video) where a
    failing score costs one text call instead of a full paid video
    generation. Advisory only, same posture as that QA judge — never
    blocks or auto-discards a script, just surfaces score/feedback for the
    user to act on (e.g. POST /scripts/{id}/regenerate) or ignore.
    Fails open on any judge-call error — a broken judge shouldn't block
    script suggestion/regeneration from returning its result."""
    try:
        parsed = _call_llm_json(_build_judge_prompt(script_result), temperature=0.3, max_tokens=400)
    except ToonScriptGenerationError as exc:
        logger.warning("Comedy judge call failed, leaving script unscored: %s", exc)
        return {"comedy_score": None, "passes_bar": None, "feedback": None, "judge_failed": True}
    return {
        "comedy_score": parsed.get("comedy_score"),
        "passes_bar": parsed.get("passes_bar"),
        "feedback": parsed.get("feedback"),
        "judge_failed": False,
    }


def generate_toon_script(persona_or_cluster, variants: Optional[list] = None, tone: str = "funny",
                          num_shots: int = 4, target_duration_seconds: int = 12,
                          character_personalities: Optional[dict] = None,
                          relationships: Optional[list] = None,
                          memories: Optional[list] = None,
                          cultures: Optional[list] = None,
                          performance_context: Optional[str] = None,
                          critique_feedback: Optional[str] = None,
                          previous_draft: Optional[dict] = None,
                          planned_scenes: Optional[list] = None) -> dict:
    """variants: the full cast for this script (list of CharacterVariant-like
    objects) — one real character writes a monologue, two or more write an
    actual scene between them (see _cast_line). character_personalities:
    optional {character_id: personality_dict}, relationships: optional list
    of serialized CharacterRelationship dicts already filtered to this
    cast — see app/routers/culturetoons.py::resolve_relationships_for_cast.
    Both are how a character's identity stays deterministic across scripts
    instead of being re-improvised by the LLM each call — see
    docs/culturix-comedy-architecture.md §3.2/§3.4. critique_feedback:
    optional prior judge_script_comedy() feedback (optionally combined with
    a human note) to explicitly address; previous_draft: the
    {hook_line, shots} dict being revised — passing both together switches
    the prompt into REVISION MODE so the model anchors on and minimally
    edits the existing draft instead of writing a new story — see
    POST /scripts/{id}/regenerate. planned_scenes: this function does NOT
    call plan_scenes() itself — the caller plans scenes first (a separate
    LLM call) and passes the result here, same reasoning as
    character_personalities/relationships being pre-resolved by the caller
    rather than fetched inside this module. Omit to keep the original
    single free-form "setting" behavior (e.g. a quick/cheap generation that
    doesn't need multi-location planning). Returns {"hook_line":
    str, "tone": str, "shots": [{"shot_number", "duration_seconds",
    "action", "expression", "dialogue", "speaker_variant_id"}, ...],
    "total_duration_seconds": int, "scenes": [{"scene_index", "description"}, ...] or None}."""
    variants = variants or []
    prompt = _build_prompt(persona_or_cluster, variants, tone, num_shots, target_duration_seconds,
                            character_personalities, relationships, memories, cultures, performance_context,
                            critique_feedback, previous_draft, planned_scenes)
    return _call_llm_for_script(prompt, tone, variants, planned_scenes)


def generate_toon_script_from_idea(idea: str, variants: Optional[list] = None, tone: str = "funny",
                                    num_shots: int = 4, target_duration_seconds: int = 12,
                                    character_personalities: Optional[dict] = None,
                                    relationships: Optional[list] = None,
                                    memories: Optional[list] = None,
                                    cultures: Optional[list] = None,
                                    performance_context: Optional[str] = None,
                                    critique_feedback: Optional[str] = None,
                                    previous_draft: Optional[dict] = None,
                                    planned_scenes: Optional[list] = None) -> dict:
    """Same shape/contract as generate_toon_script, but grounded in the
    user's own free-text scenario idea instead of a live trending Persona
    or Cluster — for when someone already knows what they want the
    character to react to and doesn't want to wait for/browse trends.
    planned_scenes: see generate_toon_script's own docstring — the caller
    plans scenes first via plan_scenes() (using this same idea as context,
    see that function) and passes the result here."""
    variants = variants or []
    context = f"User's scenario idea: {idea.strip()}"
    prompt = _build_prompt_from_context("user-provided scenario idea", context, variants, tone,
                                         num_shots, target_duration_seconds,
                                         character_personalities, relationships, memories, cultures,
                                         performance_context, critique_feedback, previous_draft, planned_scenes)
    return _call_llm_for_script(prompt, tone, variants, planned_scenes)


def format_world_draft(script_result: dict) -> str:
    """A hostless World script as readable text for a reviewer or a revision prompt. The generic
    _format_script_for_prompt shows "Visual:" and "Dialogue:", which are not the fields a World shot
    uses (subject_visual, narration in dialogue, people), so a reviewer reading it would not see the
    picture at all."""
    lines = []
    for shot in script_result.get("shots") or []:
        head = f"Shot {shot.get('shot_number')}"
        meta = [f"{shot.get('duration_seconds')}s" if shot.get("duration_seconds") else None,
                (shot.get("shot_type") or "").replace("_", " ") or None,
                f"camera: {(shot.get('camera_movement') or '').replace('_', ' ')}" if shot.get("camera_movement") else None,
                f"people: {shot.get('people')}" if shot.get("people") else None]
        head += " (" + ", ".join(m for m in meta if m) + ")" if any(meta) else ""
        lines.append(f"{head}\n  NARRATION: \"{(shot.get('dialogue') or '').strip()}\"\n"
                     f"  VISUAL: {(shot.get('subject_visual') or shot.get('visual') or '').strip()}")
    return f"Hook: {script_result.get('hook_line') or ''}\n\n" + "\n".join(lines)


def _world_context(region_label: str, subject_text: str, subject_category: Optional[str],
                    trends: Optional[list] = None, culture: Optional[dict] = None,
                    source_facts: Optional[str] = None, source_label: Optional[str] = None,
                    avoid_claims: Optional[list] = None, visual_fixes: Optional[list] = None,
                    scene_briefs: Optional[list] = None, previous_draft: Optional[dict] = None,
                    improvements: Optional[list] = None, era: Optional[dict] = None) -> str:
    """Builds the "context" string for generate_world_script, in the same
    role _source_type_and_context plays for the Persona/Cluster path — the
    thing a subject-centric World Feature is grounded in isn't a trending
    Persona/Cluster, it's a real place/phenomenon/species plus (optionally)
    real recent trend chatter about it and the region's cultural context.

    trends: plain dicts ({"title": str, "content": str}), already fetched
    and truncated by the caller (mirrors this module's existing convention
    of callers pre-resolving DB rows before they reach a prompt builder —
    see character_personalities/relationships/memories on
    generate_toon_script). culture: a single serialized Culture dict (see
    _culture_context) or None — reuses _culture_context verbatim rather
    than re-deriving its formatting here."""
    lines = [f"Region: {region_label}", f"Subject: {subject_text}"]
    if subject_category:
        lines.append(f"Category: {subject_category}")
    if trends:
        lines.append("Real, currently-trending chatter about this region/subject (for factual grounding, not to be quoted verbatim):")
        for t in trends[:5]:
            title = (t.get("title") or "").strip()
            content = (t.get("content") or "").strip()
            if title or content:
                snippet = f"{title} — {content}" if title and content else (title or content)
                lines.append(f"- {snippet[:220]}")
    context = "\n".join(lines)
    if source_facts:
        # The curated Wikipedia/UNESCO text is the ONLY licence to state a
        # specific fact — without it the model fills gaps from memory and
        # invents dates/figures (the "prompt invents data the source already
        # has" failure documented in docs/culturix-video-pipeline.md).
        context += (
            f"\n\nVERIFIED SOURCE MATERIAL ({source_label or 'curated source'}) — the ONLY source of "
            "factual claims for this video:\n"
            f"{source_facts.strip()[:5000]}\n"
            "FACT RULES: every date, number, name, and claim in the script must come from this "
            "material. Do NOT add specific facts from memory. If the material is thin, write a "
            "shorter, simpler script rather than padding it with invented detail.\n"
            "NARRATION CRAFT: this is a short-form video, not a guidebook. (1) The FIRST narration line "
            "is the hook — open on the single most striking concrete fact in the material, stated "
            "plainly; never start with 'Welcome to', 'Explore', 'Discover' or 'Nestled'. (2) One idea "
            "per shot; the last shot lands a payoff that makes the viewer see the subject differently, "
            "not a summary. (3) Pace for speech: at most ~2.4 spoken words per second of each shot's "
            "duration. (4) Every subject_visual is a concrete, filmable real-world scene (light, "
            "scale, motion, camera move) — no text overlays, maps-with-labels or infographics."
        )
    if era and era.get("label"):
        from app.services.world_era import band_for, year_text
        span = year_text(era["start_year"]) + (f" to {year_text(era['end_year'])}" if era["end_year"] != era["start_year"] else "")
        context += (
            f"\n\nPERIOD: this video is set in {era['label']} ({span}). Every person, building, tool, vehicle, "
            "weapon, garment and material in every visual must be something that existed in that place and "
            "time, described with that period's own materials, clothing and objects."
        )
        if band_for(era):
            context += (
                " Nothing modern may appear anywhere: no engines, cars, trucks, jeeps, aircraft, electric light, "
                "factories, chimneys, asphalt, khaki or any modern clothing, and no modern-looking buildings."
            )
        phases = era.get("phases") or []
        if phases:
            context += (
                "\n\nPERIOD GUIDE. What this place looked like in each phase of the story. Every shot has a "
                '"year": the calendar year its narration is about (BC as a negative integer). A shot\'s picture '
                "must match the phase that contains its year and show only what that phase's description says "
                "existed: its materials, building sizes, clothing and tools. Never draw something from a later "
                "phase, however famous it is.\n"
                + "\n".join(
                    f"- {ph['label']} ({year_text(ph['from_year'])} to {year_text(ph['to_year'])}): {ph['look']}"
                    + (f" Never show: {', '.join(ph['avoid'])}." if ph.get("avoid") else "")
                    for ph in phases)
            )
    if avoid_claims:
        context += (
            "\n\nA previous draft made these UNSUPPORTED claims — do not repeat them:\n"
            + "\n".join(f"- {c}" for c in avoid_claims[:6])
        )
    if scene_briefs:
        context += (
            f"\n\nSCENES: write exactly {len(scene_briefs)} shots, one per scene below, in this order. Each "
            "shot OPENS on a real reference photograph of that scene, so describe what moves in it and how the "
            "action continues from that opening frame, and stay true to what the scene shows. Because the "
            "photo shows real people where the scene has them, set \"people\": \"reference\" on shots whose "
            "scene contains people (ignore the \"distant\" instruction above for these) and \"none\" on "
            "shots whose scene has none. Never write faces or close-ups of people:\n"
            + "\n".join(f"{i}. {brief}" for i, brief in enumerate(scene_briefs, 1))
        )
    if visual_fixes:
        context += (
            "\n\nYour previous draft broke the PEOPLE rule. Fix exactly these and change nothing else:\n"
            + "\n".join(f"- {f}" for f in visual_fixes[:6])
        )
    if previous_draft and improvements:
        context += (
            "\n\nREVISION. An editor reviewed the current draft below. Rewrite it applying EVERY editor note. "
            "Keep what already works: the same number of shots, the same scene order, every fact the source "
            "supports. Do not add any fact that is not in the verified source material, and do not weaken a "
            "shot's action or camera movement while fixing another problem.\n\nCURRENT DRAFT:\n"
            f"{format_world_draft(previous_draft)}\n\nEDITOR NOTES:\n"
            + "\n".join(f"- {note}" for note in improvements[:8])
        )
    if culture:
        context += "\n" + _culture_context([culture])
    return context


# Character.thematic_role values that mean "explainer specialized in this
# domain" — kept in sync manually with the model's own docstring
# (app/models/character.py). Deliberately excludes subject_category's
# "genz"/"custom" (those describe content audience/catch-all, not a
# character's own specialization) — select_thematic_host below falls back
# to "comedy" for those instead.
_EXPLAINER_ROLES = {"culture", "tech", "place", "phenomenon", "species"}


def select_thematic_host(session, category: Optional[str], tone: str):
    """Auto-selects a CharacterVariant to host a World Feature, for callers
    (scripts/generate_world_feature.py) that didn't pass an explicit
    --host-variant-id. Characters are a shared cross-brand pool here — this
    intentionally does NOT scope by brand_id, matching the existing
    explicit-host-by-id flow, which already accepts any CharacterVariant
    regardless of which brand owns it.

    Desired role is "comedy" for a non-informative tone (funny/chaotic/
    satiric/etc. — reuses is_informative_tone, the same split this module
    already uses for the writer/judge prompts), else `category` itself when
    it's one of the explainer domains, else "comedy" as the broadest
    fallback (covers "genz"/"custom"/anything else) rather than finding no
    host at all.

    Returns None if no Character is tagged with the desired role yet (the
    common case today — this is a fresh categorization layer, not a
    migration, see Character.thematic_role's docstring) — callers already
    treat a None host as "pure subject footage, voiceover narration," no
    new fallback needed there."""
    from app.models.character import Character
    from app.models.character_variant import CharacterVariant

    role = "comedy" if not is_informative_tone(tone) else (category if category in _EXPLAINER_ROLES else "comedy")

    variant = (
        session.query(CharacterVariant)
        .join(Character, CharacterVariant.character_id == Character.id)
        .filter(Character.thematic_role == role, Character.is_active.is_(True), CharacterVariant.is_active.is_(True))
        .order_by(Character.updated_at.desc())
        .first()
    )
    return variant


_PEOPLE_WORDS = re.compile(
    r"\b(soldiers?|troops?|infantry(?:men)?|paratroopers?|marines?|sailors?|airmen|men|women|people|persons?|"
    r"crowds?|civilians?|children|figures?|crews?|teams?|faces?|hands?)\b", re.IGNORECASE)
_FACE_WORDS = re.compile(r"\b(faces?|facial|eyes|expressions?)\b", re.IGNORECASE)
# "Close-up of the beach" is fine; a close-up is only a problem when it is of people.
_CLOSEUP_OF_PEOPLE = re.compile(
    r"close-?ups?\b[^.]{0,60}\b(soldiers?|troops?|men|women|people|figures?|crowds?|faces?)\b|"
    r"\b(soldiers?|troops?|men|women|people|figures?|crowds?)\b[^.]{0,60}\bclose-?ups?\b", re.IGNORECASE)


def _mentions_faces(visual: str) -> bool:
    return bool(_FACE_WORDS.search(visual) or _CLOSEUP_OF_PEOPLE.search(visual))


_MOTION_VERBS = (
    "move plough plow surge race run sprint drift roll pour advance streak rise fall burst erupt sweep flow crash "
    "wade climb fly sail glide billow charge land drop swirl push rush pound fire roar swarm march rocket explode "
    "tumble lurch slam spray splash churn thunder hurtle whip dive circle descend leap jump dodge spill emerge "
    "approach storm burn blaze shake rumble skim swing sink launch scatter scramble crawl dash link fade clear "
    "break lift pull sway shoot blast strike stream cascade swell spin twist gather cross ride track rip tear "
    "billow sprint hurl bound stagger struggle heave paddle row steam cruise soar swoop plunge rain fill "
    # Added after a live audit (2026-09-24) of every shot check_world_motion had flagged across the
    # published/drafted World catalog: ~50 flagged shots, nearly all describing obvious, real motion
    # ("an axolotl swims... regrows a part of its limb", "the camera zooms in... pushes in", "a mimic
    # octopus transitions... slithering across the sand") that this list, calibrated on one earlier
    # historical/war-footage script, had no words for. Grouped by where the gap actually was rather
    # than added ad hoc, so the next genuinely new subject is less likely to reopen the same gap:
    # camera/reveal verbs
    "zoom pan tilt reveal focus "
    # everyday human action, missing even for very common verbs (a script about signing a document
    # or a scientist adjusting a dial had nothing to match)
    "open close step walk write sign seal point pick place leave gesture debate haggle clink unroll "
    "disappear generate shatter adjust raise guide complete "
    # biological/organic change (species and phenomena subjects overwhelmingly need these)
    "swim regrow mimic transition slither inflate hover trail shift hesitate deform thaw float lunge "
    "pulse survey "
    # light, energy and natural-phenomena change (aurora, lightning, bioluminescence, fusion subjects)
    "glow intensify spread hiss buzz flicker dance dissipate form illuminate shimmer converge compress "
    "heat emit freeze "
    # mechanical/vehicle motion and camera-adjacent verbs still missing after the first pass above
    # (found by re-running the same audit against the expanded list)
    "drive navigate blend travel highlight"
).split()


def _verb_forms(verb: str) -> set[str]:
    """base, -s/-es, -ing (silent-e dropped, final consonant doubled), -ed: "streak" also matches
    streaks/streaking, "descend" matches descending. Explicit forms, not stems, so "land" does not
    match "landscape" and "fire" does not match "first"."""
    forms = {verb, verb + "s", verb + "es", verb + "ing", verb + "ed"}
    if verb.endswith("e"):
        forms |= {verb[:-1] + "ing", verb + "d"}
    if verb.endswith("y"):
        forms |= {verb[:-1] + "ies", verb[:-1] + "ied"}
    forms |= {verb + verb[-1] + "ing", verb + verb[-1] + "ed"}
    return forms


_MOTION_WORDS = re.compile(
    r"\b(" + "|".join(sorted({f for v in _MOTION_VERBS for f in _verb_forms(v)}, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)
MIN_MOTION_WORDS = 2


MAX_NARRATION_WORDS = 22


def check_world_motion(shots: Optional[list]) -> list[str]:
    """Problems that make a World video render as a still image with a slow zoom: a subject
    shot whose visual describes no action, or a static camera. Measured on a real render:
    about a third of the scene motion of the earlier ones, with "static camera movement" in
    every prompt and no verbs of action in any visual."""
    problems = []
    for shot in shots or []:
        if (shot.get("shot_focus") or "").strip().lower() != "subject":
            continue
        number = shot.get("shot_number")
        visual = shot.get("subject_visual") or ""
        if len({m.group(0).lower() for m in _MOTION_WORDS.finditer(visual)}) < MIN_MOTION_WORDS:
            problems.append(f"Shot {number}: the visual is a still scene. Describe what MOVES, in time order, "
                            "with action verbs: name who or what moves, where to, and what has changed by the last frame.")
        words = len((shot.get("dialogue") or "").split())
        if words > MAX_NARRATION_WORDS:
            problems.append(f"Shot {number}: the narration is {words} words. Keep it to 18 or fewer so the shot "
                            "stays near 8 seconds (long shots render as slow, static scenes).")
        if (shot.get("camera_movement") or "").strip().lower() in ("static", ""):
            problems.append(f"Shot {number}: camera_movement is static. Use tracking, dolly, push_in, pull_out, "
                            "crane, pan_left, pan_right, tilt or orbit.")
    return problems


# Words that describe a place being lived in, not something happening. A visual made of them
# renders as a still scene with background flicker, however many motion verbs it also has.
_AMBIENT_LIFE = re.compile(
    r"\b(go(?:es|ing)? about|daily (?:li(?:fe|ves)|routine)|everyday life|interact(?:s|ing|ion|ions)?|"
    r"mov(?:e|es|ing) about|bustl\w*|thriv\w*|hustle|lively|vibrant|peaceful|serene|tranquil|"
    r"a variety of|various)\b", re.IGNORECASE)


# A picture of information rather than a place: a video model renders it as a flat card with garbled text.
_NOT_A_SCENE = re.compile(
    r"\b(maps?|infographics?|diagrams?|charts?|timelines?|title cards?|text overlays?|captions?|graphics?|"
    r"globes?|illustrations? of|painting of|drawing of)\b", re.IGNORECASE)


def check_world_action(shots: Optional[list]) -> list[str]:
    """A subject visual that is ambient life ("villagers going about their day", "a bustling market")
    instead of one event. Measured on a real draft: the AI reviewer scored such a script 67 for
    movement while every shot was scenery, so this is checked in code."""
    problems = []
    for shot in shots or []:
        if (shot.get("shot_focus") or "").strip().lower() != "subject":
            continue
        card = _NOT_A_SCENE.search(shot.get("subject_visual") or "")
        if card:
            problems.append(f'Shot {shot.get("shot_number")}: "{card.group(0)}" is not a filmable scene. Show a real '
                            "place, people or objects doing something, not a map, graphic or text.")
        match = _AMBIENT_LIFE.search(shot.get("subject_visual") or "")
        if match:
            problems.append(f'Shot {shot.get("shot_number")}: "{match.group(0)}" describes ambient life, not an event. '
                            "Replace it with ONE specific thing that happens: who does what to what, and what is "
                            "different in the last frame from the first.")
    return problems


def check_world_visuals(shots: Optional[list]) -> list[str]:
    """Problems in a hostless World script's subject shots against the PEOPLE rule: the
    renderer says "no people in frame" unless a shot has people="distant", so a visual that
    shows people without it contradicts its own render prompt, and a "distant" shot must not
    ask for faces or close-ups. [] when the visuals are consistent."""
    problems = []
    for shot in shots or []:
        if (shot.get("shot_focus") or "").strip().lower() != "subject":
            continue
        visual = shot.get("subject_visual") or ""
        people = (shot.get("people") or "none").strip().lower()
        number = shot.get("shot_number")
        if people in ("distant", "reference"):
            if _mentions_faces(visual):
                problems.append(f'Shot {number}: people is "distant" but the visual mentions faces, eyes or a '
                                "close-up. Show only small, distant, faceless figures in a wide shot.")
        elif _PEOPLE_WORDS.search(visual):
            problems.append(f'Shot {number}: the visual shows people but "people" is "none". Either set '
                            '"people" to "distant" and show them only as small faceless figures in a wide '
                            "shot, or remove every person from the visual.")
    return problems


# A biological/physical CHANGE word near a word implying it becomes visible/happens within
# the shot — as opposed to being described as an already-completed state (e.g. "an edited
# gene sequence", past tense) — flags the exact live-transformation pattern confirmed live to
# render as a warped mess: a CRISPR shot asking for a plant to visibly grow/change color right
# after an injection.
_VISIBLE_CHANGE = re.compile(
    r"\b(shows? (?:visible )?signs? of|visibly (?:grows?|changes?|transforms?|heals?)|"
    r"begins? to (?:grow|change|transform|heal)|(?:new growth|color change) (?:appears?|occurs?|begins?)|"
    r"transforms? before|visible transformation)\b", re.IGNORECASE)


def check_world_plausibility(shots: Optional[list]) -> list[str]:
    """A subject visual asking for a biological or physical transformation to become visible
    WITHIN the ~8-second shot, as the direct result of one action in it (an injection followed
    by visible plant growth, a wound visibly healing). That does not happen at video timescale
    — a video model asked to render it produces a warped, glitching result, not a time-lapse.
    [] when every visual describes a stable moment instead."""
    problems = []
    for shot in shots or []:
        if (shot.get("shot_focus") or "").strip().lower() != "subject":
            continue
        visual = shot.get("subject_visual") or ""
        match = _VISIBLE_CHANGE.search(visual)
        if match:
            problems.append(f'Shot {shot.get("shot_number")}: "{match.group(0)}" asks for a transformation to '
                            "become visible within this one shot — that does not happen at video timescale and "
                            "renders as a glitching mess. Show a stable moment instead: the action itself, or a "
                            "believable side-by-side of a treated sample next to an untreated one.")
    return problems


# Vehicle/vantage words that would normally put a driver's seat or operator's position in
# frame — paired with the subject actually being about autonomous/driverless technology (see
# check_world_autonomy), a shot mentioning one of these without also saying the seat/position
# is empty defaults, in a video model with no other instruction, to rendering a normal human
# driver — confirmed live on a Waymo Feature ("driverless taxis") whose shots never said so.
_DRIVER_VANTAGE = re.compile(
    r"\b(driver'?s?\s*seat|behind the wheel|at the wheel|cockpit|driving seat|cab(?:in)?)\b", re.IGNORECASE)
_AUTONOMY_SUBJECT = re.compile(
    r"\b(self-?driving|driverless|autonomous (?:vehicle|car|taxi|drone|robot))\b", re.IGNORECASE)
_EMPTY_SEAT_STATED = re.compile(
    r"\b(empty|no\s*(?:one|body|driver|human)|nobody|unmanned|unoccupied|vacant)\b", re.IGNORECASE)


def check_world_autonomy(shots: Optional[list], subject_text: str) -> list[str]:
    """When the subject itself is about self-driving/driverless/autonomous technology, a shot
    that puts a driver's seat or operator's position in frame without explicitly saying it is
    empty silently contradicts the subject — a video model has no built-in notion that
    "driverless" means it should omit the driver, and defaults to rendering one. [] when the
    subject isn't about autonomy, or every such shot already states the seat is empty."""
    if not _AUTONOMY_SUBJECT.search(subject_text or ""):
        return []
    problems = []
    for shot in shots or []:
        if (shot.get("shot_focus") or "").strip().lower() != "subject":
            continue
        visual = shot.get("subject_visual") or ""
        if _DRIVER_VANTAGE.search(visual) and not _EMPTY_SEAT_STATED.search(visual):
            problems.append(f'Shot {shot.get("shot_number")}: the visual puts a driver\'s seat/operator position '
                            "in frame but never says it is empty — for a driverless/autonomous subject this "
                            "renders as a normal human driver, contradicting the subject. Explicitly state the "
                            "seat is empty or otherwise make the absence of a human operator visually explicit.")
    return problems


def normalize_world_people(shots: Optional[list]) -> tuple[list, list[str]]:
    """Make each subject shot's `people` value consistent with its visual, so the render prompt
    never contradicts itself. Unknown values become "none"; a visual that shows people gets
    "distant". Returns (shots, warnings) — warnings list anything that could not be fixed."""
    warnings = []
    out = []
    for shot in shots or []:
        shot = dict(shot)
        if (shot.get("shot_focus") or "").strip().lower() == "subject":
            people = (shot.get("people") or "none").strip().lower()
            visual = shot.get("subject_visual") or ""
            if people not in ("none", "distant", "reference"):
                people = "none"
            if people == "none" and _PEOPLE_WORDS.search(visual):
                people = "distant"
                warnings.append(f"Shot {shot.get('shot_number')}: visual shows people; people set to distant")
            if people in ("distant", "reference") and _mentions_faces(visual):
                warnings.append(f"Shot {shot.get('shot_number')}: distant shot still mentions faces or a close-up")
            shot["people"] = people
        out.append(shot)
    return out, warnings


def suggest_world_duration(subject_text: str, subject_summary: str = "",
                           subject_category: Optional[str] = None) -> dict:
    """Suggest a short-form duration and narrative beat count for a subject.

    The recommendation is bounded to practical World Feature formats. It is
    guidance for the script writer, not a license to pad a simple subject;
    the final stored duration is still the sum of the generated shot timings.
    """
    fallback = {"duration_seconds": 20, "beat_count": 3, "rationale": "Standard subject explanation."}
    prompt = f"""Choose the shortest useful short-form video duration for this factual World Feature.

Subject: {subject_text}
Summary: {subject_summary[:1200]}
Category: {subject_category or 'custom'}

Use 15 seconds for one clear reveal, 20-30 seconds for a normal explanation with context,
35-45 seconds for a subject with several essential chronological beats, and 60 seconds only
when the subject truly needs a compact mini-documentary. Do not pad simple subjects. Choose
one duration from [15, 20, 30, 45, 60] and a beat_count from 1 to 5.

Return ONLY valid JSON: {{"duration_seconds": int, "beat_count": int, "rationale": "one short sentence"}}"""
    try:
        result = _call_llm_json(prompt, temperature=0.2, max_tokens=180)
        allowed = (15, 20, 30, 45, 60)
        duration = min(allowed, key=lambda value: abs(value - int(result.get("duration_seconds", 20))))
        beats = max(1, min(5, int(result.get("beat_count", 3))))
        return {"duration_seconds": duration, "beat_count": beats, "rationale": str(result.get("rationale") or fallback["rationale"])}
    except Exception:
        logger.warning("World duration suggestion failed for %r; using %ss fallback", subject_text, fallback["duration_seconds"], exc_info=True)
        return fallback


def generate_world_script(region_code: str, region_label: str, subject_text: str,
                           subject_category: Optional[str] = None,
                           trends: Optional[list] = None, culture: Optional[dict] = None,
                           host_variant: Optional[object] = None,
                           tone: str = "informative", num_shots: int = 4,
                           target_duration_seconds: int = 20,
                           source_facts: Optional[str] = None, source_label: Optional[str] = None,
                           avoid_claims: Optional[list] = None,
                           visual_fixes: Optional[list] = None,
                           scene_briefs: Optional[list] = None,
                           previous_draft: Optional[dict] = None,
                           improvements: Optional[list] = None,
                           era: Optional[dict] = None) -> dict:
    """Generates a World Feature script — a subject-centric video (a place,
    phenomenon, or species is the star) grounded in real region-filtered
    Trend rows and (optionally) the shared Culture library, for the public
    /world section. Same shape/contract as generate_toon_script_from_idea
    (returns {"hook_line", "setting", "tone", "shots", "total_duration_seconds",
    "scenes": None} — persistence is the caller's job, matching every other
    generate_* function in this module).

    host_variant: an OPTIONAL single CharacterVariant-like object acting as
    a regional host/narrator — never a cast, never required. Passed through
    to _cast_line exactly as generate_toon_script_from_idea would pass a
    single-variant cast; None produces the same empty-cast prompt behavior
    _cast_line already handles.

    tone defaults to "informative" (not "funny") because a World Feature's
    job is the same as this module's existing informative-tone branch in
    _build_prompt_from_context: show the subject at real scale, character
    (if any) as narrator, majority of shots shot_focus="subject" — this is
    exactly the machinery already built and confirmed live for exactly this
    kind of content (see that function's 2026-09-07 eclipse/hallucination
    notes). Callers may still pass any other TONE_OPTIONS value if a World
    Feature genuinely calls for a non-informative register."""
    variants = [host_variant] if host_variant is not None else []
    context = _world_context(region_label, subject_text, subject_category, trends, culture,
                             source_facts=source_facts, source_label=source_label, avoid_claims=avoid_claims,
                             visual_fixes=visual_fixes, scene_briefs=scene_briefs,
                             previous_draft=previous_draft, improvements=improvements, era=era)
    if not variants:
        # cast_line is empty with no variants (see _cast_line), which on its
        # own leaves the craft guidance's "use the cast to carry the
        # structure" language dangling with nothing to point at — spell out
        # explicitly that there is no character at all, so the model doesn't
        # invent an unnamed on-screen narrator to satisfy that guidance.
        context += (
            "\n\nNO CHARACTER — this is pure subject footage with voiceover narration, nobody "
            'on screen. Every shot must be shot_focus "subject", voiceover=true, dialogue is the '
            "narration line (no on-screen speaker), expression and blocking null. Do not invent, "
            "name, or describe any narrator/host appearing in frame. "
            "PEOPLE: every shot has a \"people\" field. The default is \"none\": the renderer then adds "
            "\"no people in frame\", so the subject_visual must show none (landscape, structures, "
            "objects, animals, ships, weather, light, camera movement: only things that existed in the period). When the event IS its "
            "people (a landing, a march, a ceremony, a crowd) set \"people\": \"distant\" on the shots "
            "that show them, and describe them only as small, distant, faceless groups in WIDE shots: "
            "never faces, never close-ups, no graphic violence, and no named units, insignia or "
            "specific equipment models unless the source mentions them. Never describe people while "
            "\"people\" is \"none\".\n"
            "MOTION: this is video, not a slideshow. A still scene renders as a still image with a slow "
            "zoom. Every subject_visual must describe ACTION IN TIME ORDER, using present-tense verbs: what "
"moves and how, from the start of the shot to its end: who or what moves, where to, and what has "
            "changed by the last frame. Take every "
            "picture from THIS subject's own source material, never from a different subject: build each shot "
            "from the concrete things the source names (its people, machines, buildings, animals, weather, "
            "objects) and show them DOING something, not sitting in a landscape. Every shot needs a moving camera_movement (never "
            "\"static\": use tracking, dolly, push_in, pull_out, crane, pan_left, pan_right, tilt or "
            "orbit) and shot_type should vary across the video. NARRATION LENGTH: each shot's dialogue is "
            "14 to 18 words (about 6 to 7 seconds spoken), so shots stay near 8 seconds: a long shot renders "
            "as a slow, static scene, and a very short line leaves the shot silent. People wear what the period and place required, never modern clothing.\n"
            "NO AMBIENT LIFE: never write that people 'go about their daily lives', that a place is 'bustling', "
            "'thriving', 'vibrant' or 'peaceful', or that people 'interact'. That is scenery. Each subject_visual is "
            "ONE specific event with a clear before and after, naming who does what to what.\n"
            "ENGAGEMENT: the viewer decides in three seconds. Line 1 drops them into a moment of stakes or "
            "contrast using the most striking fact in the source (the scale of the force, the odds, the "
            "surprise), never a label or a date-and-definition opener. Each later line ESCALATES or TURNS "
            "(cause, then effect, then consequence); it never lists. The last line reframes what the viewer "
            "just watched. In EVERY shot something must CHANGE between its first and last frame (a fleet "
            "appears out of haze, a ramp drops and men pour out, a wall of smoke swallows the shore), told "
            "as an event, not a scene. Vary scale and angle shot to shot (wide establishing, low tracking "
            "along the action, a close detail of machinery or water, an aerial), and let each visual show "
            "what its narration line has just said.\n"
            "PLAUSIBILITY: never describe a biological or physical transformation becoming VISIBLE within "
            "one ~8-second shot as the direct result of a single action (a plant 'shows signs of "
            "transformation' right after an injection, a wound visibly healing, a cell visibly dividing "
            "into a different organism) — that does not happen at video timescale, and asking a video model "
            "to render it produces a warped, glitching mess, not a time-lapse. Show a real, STABLE moment "
            "instead: the action itself (the injection, the cut, the measurement), or a believable "
            "side-by-side of a treated sample next to an untreated one, never the transformation itself "
            "occurring on camera.\n"
            "AUTONOMY: if the subject is about a self-driving, driverless or autonomous vehicle or system, "
            "a video model has no built-in notion that 'driverless' means it should omit the driver — left "
            "unstated, it defaults to rendering a normal human driver, contradicting the subject. Every shot "
            "that shows the vehicle from an angle where a driver's seat or operator's position would "
            "normally be visible must explicitly say it is EMPTY (\"the driver's seat is empty, no one at "
            "the wheel\") or otherwise make the absence of a human operator visually explicit."
        )
    prompt = _build_prompt_from_context("real-world region/subject", context, variants, tone,
                                         num_shots, target_duration_seconds)
    return _call_llm_for_script(prompt, tone, variants, planned_scenes=None)


_STOPWORDS = frozenset(
    "the a an and or but of in on at to for from by with as is are was were be been being it its this that these those "
    "their his her they them he she we you i not no than then so such into onto over under about after before while "
    "during also more most many much some any each other one two three".split())
CLAIM_SUPPORT_COVERAGE = 0.85


def _content_stems(text: str) -> list[str]:
    """Lowercase content words, crudely stemmed so "declared", "declaring" and "declares" match."""
    stems = []
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if word in _STOPWORDS or (len(word) < 3 and not word.isdigit()):
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        stems.append(word)
    return stems


def claim_supported_by_source(claim: str, source_facts: str) -> bool:
    """True when ONE sentence of the source contains every number in the claim and at least
    CLAIM_SUPPORT_COVERAGE of its content words. The fact-checker model is not deterministic: it flagged "The
    United States declared its independence on July 4, 1776" when the source says exactly that, so a curator
    could fix a real problem and still never clear the warning. Requiring all of it inside a single sentence
    keeps real inventions ("a quill pen scratches") flagged: their invented words are not in any sentence."""
    wanted = _content_stems(claim)
    if not wanted:
        return False
    numbers = {w for w in wanted if w.isdigit()}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", source_facts or ""):
        have = set(_content_stems(sentence))
        if numbers <= have and sum(1 for w in wanted if w in have) / len(wanted) >= CLAIM_SUPPORT_COVERAGE:
            return True
    return False


def _narration_for_fact_check(script_result: dict) -> str:
    """The headline and the spoken lines only. The generic script formatter also prints each shot's picture
    description, and the fact-checker then flagged pictorial detail ("sealed with a wax seal") that no viewer
    hears and that the claim fixer, which edits narration, could never remove."""
    lines = [f"Headline: {script_result.get('hook_line') or ''}"]
    for shot in script_result.get("shots") or []:
        text = (shot.get("dialogue") or "").strip()
        if text:
            lines.append(f"Shot {shot.get('shot_number')}: {text}")
    return "\n".join(lines)


def judge_world_grounding(script_result: dict, source_facts: str) -> dict:
    """Fact-checks a World script against its verified source material via a
    SEPARATE LLM call (a fresh critic, same posture as judge_script_comedy).
    The tone judge scores craft, not accuracy — this is the accuracy gate.
    Returns {"grounded": bool|None, "unsupported_claims": [str], "judge_failed": bool};
    fails open (grounded=None) so a broken judge never blocks a draft."""
    prompt = f"""You are a strict fact-checker for a short educational video.

VERIFIED SOURCE MATERIAL:
{source_facts.strip()[:5000]}

WHAT THE VIEWER WILL HEAR AND READ:
{_narration_for_fact_check(script_result)}

List every specific factual claim in the headline and narration above (dates, numbers, names, causes,
superlatives) that is NOT supported by the source material. General framing and transitions are fine; only
flag concrete claims the source does not back up. Quote each claim exactly as it appears above. The pictures
that accompany the narration are illustrations and are checked separately: do not judge them.

Return ONLY valid JSON: {{"unsupported_claims": [string], "grounded": boolean (true only if the list is empty)}}"""
    try:
        parsed = _call_llm_json(prompt, temperature=0.1, max_tokens=500)
    except ToonScriptGenerationError as exc:
        logger.warning("Grounding judge call failed, leaving draft unchecked: %s", exc)
        return {"grounded": None, "unsupported_claims": [], "judge_failed": True}
    flagged = [str(c) for c in (parsed.get("unsupported_claims") or []) if c]
    dismissed = [c for c in flagged if claim_supported_by_source(c, source_facts)]
    claims = [c for c in flagged if c not in dismissed]
    if dismissed:
        logger.info("Grounding judge flagged %d claim(s) that a source sentence states; dismissed: %s",
                    len(dismissed), dismissed)
    result = {"grounded": not claims, "unsupported_claims": claims, "judge_failed": False}
    if dismissed:
        result["dismissed"] = dismissed
    return result


def fix_unsupported_claims(script_result: dict, claims: list, source_facts: str) -> Optional[dict]:
    """Rewrite ONLY the narration lines (and the hook) that hold claims the source does not support, using
    only what the source says. Returns a copy of the script with those lines replaced, or None if nothing
    could be fixed.

    Why this is separate from regenerating the script: a full rewrite re-invents the same flourish ("a quill
    pen sealed the fate of a new nation") and the caller only kept a rewrite that scored higher overall, so a
    fix that removed the claim but dipped the score was thrown away and the claim stayed. A narrow edit of the
    named lines does not disturb the rest."""
    numbered = "\n".join(f"Shot {s.get('shot_number')}: {(s.get('dialogue') or '').strip()}"
                         for s in script_result.get("shots") or [])
    prompt = f"""A fact-checker found claims in a short educational video script that the verified source does not support.

VERIFIED SOURCE MATERIAL (the only allowed source of facts):
{source_facts.strip()[:5000]}

HOOK LINE: {script_result.get("hook_line") or ""}
NARRATION:
{numbered}

UNSUPPORTED CLAIMS:
{chr(10).join("- " + str(c) for c in claims[:8])}

Rewrite ONLY the hook line and the narration lines that contain these claims. Each rewrite:
- states only facts the source material states (drop embellishment, colour, causes and superlatives the source does not give);
- keeps the line's place in the story and stays {MAX_NARRATION_WORDS - 6} to {MAX_NARRATION_WORDS - 4} words;
- is plain, concrete and specific, not vague.
Leave every other line out of your answer.

Return ONLY valid JSON: {{"hook_line": string or null (null if the hook needs no change), "lines": [{{"shot_number": integer, "dialogue": string}}]}}"""
    try:
        parsed = _call_llm_json(prompt, temperature=0.2, max_tokens=700)
    except ToonScriptGenerationError as exc:
        logger.warning("Claim fixer call failed: %s", exc)
        return None
    shots = [dict(s) for s in script_result.get("shots") or []]
    by_number = {s.get("shot_number"): s for s in shots}
    changed = 0
    for item in parsed.get("lines") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("dialogue") or "").strip()
        shot = by_number.get(item.get("shot_number"))
        if shot is None or not text or len(text.split()) > MAX_NARRATION_WORDS or text == (shot.get("dialogue") or "").strip():
            continue
        shot["dialogue"] = text
        changed += 1
    hook = str(parsed.get("hook_line") or "").strip()
    new_hook = hook if hook and hook != (script_result.get("hook_line") or "").strip() else script_result.get("hook_line")
    if new_hook != script_result.get("hook_line"):
        changed += 1
    if not changed:
        return None
    return {**script_result, "shots": shots, "hook_line": new_hook}


def generate_toon_script_continuing_episode(prior_parts_summary: str, idea: str, variants: Optional[list] = None,
                                             tone: str = "funny", num_shots: int = 4,
                                             target_duration_seconds: int = 12,
                                             character_personalities: Optional[dict] = None,
                                             relationships: Optional[list] = None,
                                             memories: Optional[list] = None,
                                             cultures: Optional[list] = None,
                                             performance_context: Optional[str] = None,
                                             planned_scenes: Optional[list] = None) -> dict:
    """Same shape/contract as generate_toon_script_from_idea, but grounded in
    a synopsis of an episode's prior parts too (see
    app/routers/culturetoons.py's _episode_synopsis) — the next part is
    written with awareness of what already happened instead of starting
    cold each time, which is what episode stitching otherwise leaves to the
    user to maintain by hand across separately-suggested scripts.
    planned_scenes: see generate_toon_script's own docstring — the caller
    plans scenes first via plan_scenes() and passes the result here."""
    variants = variants or []
    context = (
        f"What has happened so far in this story, in order:\n{prior_parts_summary.strip()}\n\n"
        f"What should happen in this NEXT part: {idea.strip()}"
    )
    prompt = _build_prompt_from_context(
        "the ongoing story so far, and what should happen in this next part", context, variants, tone,
        num_shots, target_duration_seconds, character_personalities, relationships, memories, cultures,
        performance_context, planned_scenes=planned_scenes,
    )
    prompt += (
        "\n\nThis is a continuation, not a new story — do not recap, re-introduce the characters, "
        "or restate what already happened. Continue directly from where the story left off."
    )
    return _call_llm_for_script(prompt, tone, variants, planned_scenes)


def build_kling_prompt(shots: list, element_names) -> str:
    """Assembles Kling Omni's multi-shot DSL string ("shot n, m, words; ...")
    from stored shots + registered element name(s). Raises
    ToonScriptGenerationError on any structural problem — empty/too-many
    shots, non-contiguous shot_number values, an out-of-bounds total
    duration, or a per-shot built prompt exceeding Kling's 512-char cap.

    element_names accepts either a single string (single-character script,
    unchanged from before) or a dict of {variant_id: element_name, ...} for
    a multi-character script — each shot's speaker_variant_id (or the dict's
    first entry, as the "primary" speaker, when a shot doesn't set one)
    picks which @ElementName is referenced. @{element_name} is referenced
    in every shot segment (not just the first) — the safer
    explicit-over-implicit default; cheap to change here alone if a live
    test shows Kling tracks characters across shots without repeating the
    reference."""
    if not shots:
        raise ToonScriptGenerationError("Cannot build a Kling prompt from an empty shots list")
    if len(shots) > KLING_MAX_SHOTS:
        raise ToonScriptGenerationError(f"Kling supports at most {KLING_MAX_SHOTS} shots, got {len(shots)}")

    if isinstance(element_names, str):
        element_map: dict = {}
        default_element = element_names
    else:
        element_map = dict(element_names)
        if not element_map:
            raise ToonScriptGenerationError("build_kling_prompt requires at least one element name")
        default_element = next(iter(element_map.values()))

    expected_numbers = list(range(1, len(shots) + 1))
    actual_numbers = [s.get("shot_number") for s in shots]
    if actual_numbers != expected_numbers:
        raise ToonScriptGenerationError(
            f"shot_number values must be a contiguous 1..N sequence, got {actual_numbers}"
        )

    total_seconds = sum(s.get("duration_seconds", 0) for s in shots)
    if not (MIN_TOTAL_SECONDS <= total_seconds <= KLING_MAX_TOTAL_SECONDS):
        raise ToonScriptGenerationError(
            f"Total shot duration must be between {MIN_TOTAL_SECONDS} and {KLING_MAX_TOTAL_SECONDS}s for Kling, got {total_seconds}s"
        )

    segments = []
    for shot in shots:
        duration = shot.get("duration_seconds")
        if not isinstance(duration, int) or duration < 1:
            raise ToonScriptGenerationError(
                f"Shot {shot.get('shot_number')} has an invalid duration_seconds: {duration}"
            )

        speaker_variant_id = shot.get("speaker_variant_id")
        element_name = element_map.get(speaker_variant_id, default_element) if element_map else default_element

        parts = [f"@{element_name}"]
        shot_type = shot.get("shot_type")
        if shot_type:
            parts.append(f"{shot_type.replace('_', ' ')} shot")
        camera_movement = shot.get("camera_movement")
        if camera_movement:
            parts.append(f"{camera_movement.replace('_', ' ')} camera movement")
        visual = (shot.get("visual") or "").strip()
        if visual:
            parts.append(visual)
        action = (shot.get("action") or "").strip()
        if action:
            parts.append(action)
        expression = shot.get("expression")
        if expression:
            parts.append(f"{expression.lower()} expression")
        dialogue = shot.get("dialogue")
        if dialogue:
            delivery = (shot.get("dialogue_delivery") or "").strip()
            parts.append(f'saying "{dialogue}"' + (f" ({delivery} delivery)" if delivery else ""))

        text = ", ".join(parts) + "."
        if len(text) > _MAX_SHOT_PROMPT_CHARS:
            raise ToonScriptGenerationError(
                f"Shot {shot['shot_number']}'s built prompt text exceeds Kling's "
                f"{_MAX_SHOT_PROMPT_CHARS}-char limit ({len(text)} chars)"
            )
        segments.append(f"shot {shot['shot_number']}, {duration}, {text}")

    return "; ".join(segments) + ";"
