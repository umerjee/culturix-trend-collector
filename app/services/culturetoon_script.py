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
from datetime import datetime, timedelta
from itertools import zip_longest
from typing import Optional

from app.models.persona import Persona
from app.models.cluster import Cluster

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

TONE_OPTIONS = ["funny", "dramatic", "satiric", "sad", "wholesome", "chaotic", "deadpan"]

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
MAX_SHOTS = 15
MIN_TOTAL_SECONDS = 3
MAX_TOTAL_SECONDS = 60
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
                                critique_feedback: Optional[str] = None) -> str:
    cast_line = _cast_line(variants, source_type, character_personalities)
    relationship_line = _relationship_context(relationships)
    memory_line = _memory_context(memories)
    culture_line = _culture_context(cultures)
    performance_line = performance_context or ""
    critique_line = (
        f"\nA critic reviewed an earlier draft of this exact premise and said: \"{critique_feedback}\" "
        "— this revision MUST specifically fix that, not just produce another similar draft.\n"
        if critique_feedback else ""
    )
    speaker_field = (
        '\n- "speaker_name" is the exact name of which listed character is acting/speaking in '
        "that shot (required when more than one character is listed; omit or null otherwise)."
        if len(variants) > 1 else ""
    )
    speaker_key = ", speaker_name (string or null)" if len(variants) > 1 else ""

    return f"""You are a scriptwriter for short character-based comedy skits for
social video, grounded in the {source_type} below. The tone must be: {tone}.

{context}
{cast_line}
{relationship_line}
{memory_line}
{culture_line}
{performance_line}
{critique_line}
Aim for around {num_shots} shots totaling about {target_duration_seconds} seconds, though you
may adjust within the hard limits below if it better serves the joke.

Comedy craft — the single biggest thing separating a flat skit from a genuinely funny one:
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

Requirements:
- Between {MIN_SHOTS} and {MAX_SHOTS} shots. shot_number must be 1, 2, 3... with no gaps.
- Each shot's duration_seconds is a whole number >= 1. The SUM of all shots'
  duration_seconds must be between {MIN_TOTAL_SECONDS} and {MAX_TOTAL_SECONDS} (hard limits).
- "visual" describes the staging: props, environment, positioning, what's physically in frame
  (max ~20 words) — e.g. "holding a massive drum, confetti mid-air, a family tree scroll unrolled
  across the floor," not a vague scene description.
- "action" describes the character's specific physical performance/movement in that shot (max
  ~15 words) — a concrete, exaggerated physical beat (e.g. "sweating, dancing manically" or
  "aggressively taps a stopwatch"), not a generic verb like "gestures" or "reacts."
- "expression" is one of exactly these values, or null if not relevant: {EXPRESSION_NAMES}.
- "dialogue" is what the character says out loud in that shot, or null for a
  silent/reaction-only beat. Give it real voice — specific, escalating, in-character, not a
  generic informative sentence.
- "dialogue_delivery" is a short (2-4 word) delivery-style tag for how the line is performed
  (e.g. "Loud & Hyped", "Deadpan / Robotic", "Whispered, intense") — null when dialogue is null.
- hook_line is a punchy, stand-alone opening line/on-screen text summarizing the skit (max 15 words).{speaker_field}

Return ONLY valid JSON with exactly these keys:
- hook_line: string
- shots: array of objects, each with exactly: shot_number (int), duration_seconds (int),
  visual (string), action (string), expression (string or null), dialogue (string or null),
  dialogue_delivery (string or null){speaker_key}

Return ONLY the JSON object, no other text."""


def _build_prompt(persona_or_cluster, variants: list, tone: str, num_shots: int, target_duration_seconds: int,
                   character_personalities: Optional[dict] = None, relationships: Optional[list] = None,
                   memories: Optional[list] = None, cultures: Optional[list] = None,
                   performance_context: Optional[str] = None, critique_feedback: Optional[str] = None) -> str:
    source_type, context = _source_type_and_context(persona_or_cluster)
    return _build_prompt_from_context(source_type, context, variants, tone, num_shots, target_duration_seconds,
                                       character_personalities, relationships, memories, cultures, performance_context,
                                       critique_feedback)


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


def _call_llm_for_script(prompt: str, tone: str, variants: list) -> dict:
    parsed = _call_llm_json(prompt, temperature=0.7, max_tokens=900)
    shots = parsed.get("shots") or []
    total = sum(s.get("duration_seconds", 0) for s in shots) if shots else 0
    return {
        "hook_line": parsed.get("hook_line"),
        "tone": tone,
        "shots": _assign_speakers(shots, variants),
        "total_duration_seconds": parsed.get("total_duration_seconds") or total,
    }


def _build_judge_prompt(script_result: dict) -> str:
    hook = script_result.get("hook_line") or ""
    shot_lines = []
    for s in script_result.get("shots") or []:
        parts = [f"Shot {s.get('shot_number')}"]
        if s.get("visual"):
            parts.append(f"Visual: {s['visual']}")
        if s.get("action"):
            parts.append(f"Action: {s['action']}")
        if s.get("dialogue"):
            delivery = f" ({s['dialogue_delivery']})" if s.get("dialogue_delivery") else ""
            parts.append(f'Dialogue{delivery}: "{s["dialogue"]}"')
        shot_lines.append(" | ".join(parts))
    shots_text = "\n".join(shot_lines)

    return f"""You are a blunt, strict comedy critic reviewing a short skit script before it
gets turned into video. Score it honestly — most first drafts are too safe and should NOT
pass; a passing score should be rare, reserved for scripts that are genuinely specific and
committed, not just "fine."

Hook: {hook}

{shots_text}

Score against these specific criteria (the exact bar the writer was given):
- SPECIFICITY: concrete props/numbers/particulars, not generic statements a real person might
  mildly say.
- ESCALATION: each beat tops the one before it, not a flat list of parallel/same-size beats.
- COMMITMENT: characters pushed to an absurd, committed extreme, not a safe/mild version.

Return ONLY valid JSON with exactly these keys:
- comedy_score: integer 0-100
- passes_bar: boolean (true only if genuinely funny and specific — most drafts should fail)
- feedback: string, 1-3 sentences of SPECIFIC actionable critique — name the exact line that's
  too generic/mild and say what direction to push it, don't just say "make it funnier"

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
                          critique_feedback: Optional[str] = None) -> dict:
    """variants: the full cast for this script (list of CharacterVariant-like
    objects) — one real character writes a monologue, two or more write an
    actual scene between them (see _cast_line). character_personalities:
    optional {character_id: personality_dict}, relationships: optional list
    of serialized CharacterRelationship dicts already filtered to this
    cast — see app/routers/culturetoons.py::resolve_relationships_for_cast.
    Both are how a character's identity stays deterministic across scripts
    instead of being re-improvised by the LLM each call — see
    docs/culturix-comedy-architecture.md §3.2/§3.4. critique_feedback:
    optional prior judge_script_comedy() feedback to explicitly address —
    see POST /scripts/{id}/regenerate. Returns {"hook_line":
    str, "tone": str, "shots": [{"shot_number", "duration_seconds",
    "action", "expression", "dialogue", "speaker_variant_id"}, ...],
    "total_duration_seconds": int}."""
    variants = variants or []
    prompt = _build_prompt(persona_or_cluster, variants, tone, num_shots, target_duration_seconds,
                            character_personalities, relationships, memories, cultures, performance_context,
                            critique_feedback)
    return _call_llm_for_script(prompt, tone, variants)


def generate_toon_script_from_idea(idea: str, variants: Optional[list] = None, tone: str = "funny",
                                    num_shots: int = 4, target_duration_seconds: int = 12,
                                    character_personalities: Optional[dict] = None,
                                    relationships: Optional[list] = None,
                                    memories: Optional[list] = None,
                                    cultures: Optional[list] = None,
                                    performance_context: Optional[str] = None,
                                    critique_feedback: Optional[str] = None) -> dict:
    """Same shape/contract as generate_toon_script, but grounded in the
    user's own free-text scenario idea instead of a live trending Persona
    or Cluster — for when someone already knows what they want the
    character to react to and doesn't want to wait for/browse trends."""
    variants = variants or []
    context = f"User's scenario idea: {idea.strip()}"
    prompt = _build_prompt_from_context("user-provided scenario idea", context, variants, tone,
                                         num_shots, target_duration_seconds,
                                         character_personalities, relationships, memories, cultures,
                                         performance_context, critique_feedback)
    return _call_llm_for_script(prompt, tone, variants)


def generate_toon_script_continuing_episode(prior_parts_summary: str, idea: str, variants: Optional[list] = None,
                                             tone: str = "funny", num_shots: int = 4,
                                             target_duration_seconds: int = 12,
                                             character_personalities: Optional[dict] = None,
                                             relationships: Optional[list] = None,
                                             memories: Optional[list] = None,
                                             cultures: Optional[list] = None,
                                             performance_context: Optional[str] = None) -> dict:
    """Same shape/contract as generate_toon_script_from_idea, but grounded in
    a synopsis of an episode's prior parts too (see
    app/routers/culturetoons.py's _episode_synopsis) — the next part is
    written with awareness of what already happened instead of starting
    cold each time, which is what episode stitching otherwise leaves to the
    user to maintain by hand across separately-suggested scripts."""
    variants = variants or []
    context = (
        f"What has happened so far in this story, in order:\n{prior_parts_summary.strip()}\n\n"
        f"What should happen in this NEXT part: {idea.strip()}"
    )
    prompt = _build_prompt_from_context(
        "the ongoing story so far, and what should happen in this next part", context, variants, tone,
        num_shots, target_duration_seconds, character_personalities, relationships, memories, cultures,
        performance_context,
    )
    prompt += (
        "\n\nThis is a continuation, not a new story — do not recap, re-introduce the characters, "
        "or restate what already happened. Continue directly from where the story left off."
    )
    return _call_llm_for_script(prompt, tone, variants)


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
