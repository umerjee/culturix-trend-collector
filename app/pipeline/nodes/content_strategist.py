"""
Agent 4 — Content Strategist
Uses Qwen-max (via Alibaba Dashscope) to generate personalized content ideas per user.
Falls back to Claude if Qwen is unavailable.

Generates exactly one idea per given trend cluster (not a fixed batch of 10) — the
dashboard links each idea directly to the specific trend it came from, so this needs
to produce ideas 1:1 with whatever cluster list it's handed. The proactive pipeline
run calls this with the top 3 (most relevant) clusters per profile; the on-demand
"Generate content" button (app/main.py's POST /api/generate-idea) calls the exact
same function with a single-cluster list — one code path for both.
"""
import json
import logging
import os
from typing import Optional
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.content_strategist")

# How many of a profile's relevance-ranked clusters get an idea generated
# automatically at digest-build time. The rest are on-demand only (see
# POST /api/generate-idea in app/main.py) — most trends never cost a
# generation call unless a user actually asks for one.
PROACTIVE_CLUSTER_COUNT = 3

_ALL_MEDIA = ["video", "photo", "text"]
_MEDIUM_STYLES = {
    "video": ["short video", "talking head", "GRWM", "duet", "tutorial", "POV skit", "reaction"],
    "photo": ["carousel", "single image", "infographic", "before/after photo"],
    "text": ["text post", "thread", "quote card", "poll"],
}


def _get_qwen_client():
    # Dashscope has two separate regional deployments (China: dashscope.aliyuncs.com,
    # International: dashscope-intl.aliyuncs.com) with non-interchangeable API keys.
    # This account's key is provisioned on the international side — confirmed live
    # against dashscope.aliyuncs.com (401 InvalidApiKey) vs dashscope-intl.aliyuncs.com
    # (succeeds) before making this the default.
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["QWEN_API_KEY"],
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )


def _get_claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _history_note(cluster: dict) -> str:
    """Renders the recurrence context trend_historian.py attaches to cluster['history']
    into a short phrase the prompt can use to ground ideas in real pattern data
    (e.g. an actual weekly Friday spike) instead of treating every trend as brand new."""
    history = cluster.get("history")
    if not history:
        return "first time we've seen this trend, no history yet"

    count = history.get("occurrence_count") or 1
    pattern = history.get("recurrence_pattern") or "unclear"
    dominant_day = history.get("dominant_day_of_week")

    if pattern == "weekly" and dominant_day is not None:
        return f"seen {count} times before, recurs weekly (usually {_WEEKDAY_NAMES[dominant_day]})"
    if pattern == "yearly":
        return f"seen {count} times before, recurs yearly around this time of year"
    if pattern == "sustained":
        return f"seen {count} times before, an ongoing/sustained interest"
    if pattern == "spike":
        return f"seen {count} time(s) before, tied to a one-off event — likely a short-lived spike"
    return f"seen {count} time(s) before, pattern still unclear"


def _build_prompt(profile: dict, clusters: list[dict], top_signals: Optional[list[dict]] = None) -> str:
    """Builds a prompt asking for exactly len(clusters) ideas, one per cluster, IN THE
    SAME ORDER as the input list — the caller (not the model) is responsible for
    tagging each returned idea with its cluster_index, since trusting an LLM to
    self-report a numeric index reliably is a needless failure mode to design around."""
    niche = profile.get("industry_niche") or "general brand"
    platforms = ", ".join(profile.get("target_platforms") or ["TikTok", "Instagram"])
    tones = ", ".join(profile.get("content_tones") or ["authentic"])
    goals = ", ".join(profile.get("content_goals") or ["brand awareness"])
    tags = ", ".join(profile.get("persona_tags") or [])
    age_min = profile.get("target_age_min") or 18
    age_max = profile.get("target_age_max") or 35
    count = len(clusters)

    # Empty/unset preferred_formats means "no restriction" — existing profiles
    # created before this field existed, and new ones that haven't touched the
    # setting, must keep getting all three media types, not silently zero.
    allowed_media = profile.get("preferred_formats") or _ALL_MEDIA
    media_styles_ref = ", ".join(
        f"{medium} ({', '.join(_MEDIUM_STYLES[medium])})" for medium in allowed_media if medium in _MEDIUM_STYLES
    )

    # example_posts (verbatim real posts clusterer.py extracted) is the one
    # field in a cluster that actually contains concrete named entities — the
    # real celebrity names, movie titles, event names, etc. Dropping it (as
    # this used to) leaves the model with only a paraphrased theme label to
    # work from, which is exactly how ideas end up as generic template fill
    # ("this celebrity feud") with nothing real to name.
    cluster_summary = json.dumps(
        [{"name": c.get("name"), "description": c.get("description"), "emotional_theme": c.get("emotional_theme"),
          "example_posts": (c.get("example_posts") or [])[:3],
          "history": _history_note(c)}
         for c in clusters],
        ensure_ascii=False,
    )

    # top_signals is the actual RAG result — real posts retrieved via semantic
    # search against this specific profile's niche/tags/platforms, not the
    # same generic cluster list every profile gets. Ground the prompt in these
    # when available so content is genuinely personalized, not just themed.
    signal_texts = [
        s.get("text", "").strip()
        for s in (top_signals or [])
        if s.get("text", "").strip()
    ][:8]
    signals_section = (
        f"\nSpecific posts trending right now that match this exact audience "
        f"(retrieved via semantic search on their niche/tone/platforms):\n"
        f"{json.dumps(signal_texts, ensure_ascii=False)}\n"
        if signal_texts else ""
    )

    return f"""You are an expert content strategist for {niche}.

Target audience:
- Age: {age_min}–{age_max}
- Platforms: {platforms}
- Tone: {tones}
- Goals: {goals}
- Persona types: {tags or "general audience"}

Today's trending cultural signals (summarized, each with its "history" — how often
and in what pattern we've observed it before):
{cluster_summary}
{signals_section}
Generate EXACTLY {count} content idea{"s" if count != 1 else ""} — ONE per trend above, IN THE SAME ORDER
they're listed. Idea 1 must be about trend 1, idea 2 about trend 2, and so on — do not
skip, reorder, merge, or combine trends.
Where a trend's history shows a real recurring pattern (e.g. "recurs weekly, usually
Friday" or "recurs yearly"), lean into that in posting_time/trend_connection instead
of treating it as a one-off — e.g. timing the post ahead of a known recurring spike.
Treat "likely a short-lived spike" trends as timely/newsjacking, not evergreen.
Each idea must be tailored specifically to the brand's niche, tone, and audience.
{"Prefer ideas that connect to the specific posts above where relevant — they're what this exact audience is engaging with right now, not just the general theme." if signal_texts else ""}

CRITICAL — every idea must name the actual real, specific thing the trend is about:
the real person's name, the real movie/show title, the real event, the real product —
whatever the example_posts and signals above actually reference. Read them and extract
the specific names. Do NOT write generic placeholder phrasing like "this celebrity feud",
"a movie reboot", "the drama" — that is a rejected idea, not a usable one.

This creator only makes these content mediums: {", ".join(allowed_media)}. Every idea's
"medium" must be exactly one of these, and "format" must be a specific style within that
medium — allowed styles per medium: {media_styles_ref}. Do not suggest a medium outside
this list under any circumstances, even if a trend would suit a different medium better —
pick whichever allowed medium fits best instead.
If "video" is not in the allowed list, do not suggest video-only viral mechanics like
"duet bait" or "challenge" for any idea.

Return ONLY a valid JSON array with exactly {count} object{"s" if count != 1 else ""}. Each object must have these exact keys:
- hook: attention-grabbing opening line or video hook (max 15 words)
- caption: full post caption with 3-5 relevant hashtags (50-100 words)
- cta: clear call to action (max 10 words)
- medium: exactly one of {allowed_media} — the content medium this idea actually is
- music_mood: background music style for TikTok/Reels (e.g. "Dark hypnotic trap", "Upbeat indie pop") — still fill this in even for non-video ideas, in case the creator adds a voiceover/music layer later
- platform: best platform for this specific idea
- trend_connection: which trend this taps into and why it works (max 20 words)
- format: a specific style within the chosen medium (see the allowed styles per medium above)
- video_prompt: ONLY if medium is "video" — cinematic scene description for AI video generation (subject, setting, camera movement, lighting, visual style, max 40 words). If medium is not "video", set this to an empty string "".
- viral_angle: the specific viral mechanism that makes this shareable — e.g. "hot take", "myth-bust", "POV", "transformation", "challenge", "reaction" (video-only mechanics like "duet bait" only if medium is "video") (max 12 words)
- posting_time: optimal day + time with one-line reasoning (e.g. "Thursday 6–8 PM EST — peak Gen Z scroll window")
- hashtag_strategy: exactly 5 hashtags mixing broad reach + niche community, space-separated (e.g. "#quietluxury #ootd #slowfashion #aestheticlife #outfitinspo")

Return ONLY the JSON array, no other text."""


def _parse_ideas(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _generate_ideas_for_clusters(profile: dict, clusters: list[dict], top_signals: Optional[list[dict]] = None) -> list[dict]:
    """Generates exactly len(clusters) ideas, one per cluster, in the same order as
    the input list. Used both for proactive top-3 generation and the on-demand
    single-cluster endpoint — one prompt-building/parsing path for both."""
    if not clusters:
        return []

    prompt = _build_prompt(profile, clusters, top_signals)
    if os.getenv("QWEN_API_KEY"):
        qwen = _get_qwen_client()
        response = qwen.chat.completions.create(
            model="qwen-max",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        raw = response.choices[0].message.content
    else:
        client = _get_claude_client()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000 * len(clusters),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text

    ideas = _parse_ideas(raw)
    if len(ideas) != len(clusters):
        logger.warning(
            "Idea count mismatch: asked for %d, got %d — truncating/padding is not "
            "attempted, caller must handle a short list", len(clusters), len(ideas),
        )
    return ideas


def generate_content(state: PipelineState) -> PipelineState:
    matches = state.get("persona_matches", [])
    if not matches:
        logger.warning("No persona matches — skipping content generation")
        state["generated_content"] = []
        return state

    results = []
    for match in matches:
        user_id = match["user_id"]
        profile = match["profile"]
        clusters = match.get("clusters", [])
        top_signals = match.get("top_signals", [])
        proactive_clusters = clusters[:PROACTIVE_CLUSTER_COUNT]

        ideas = []
        try:
            ideas = _generate_ideas_for_clusters(profile, proactive_clusters, top_signals)
            # Tag by position — proactive_clusters is clusters[:N], so its indices
            # already match the position each cluster holds in the full `clusters`
            # list stored on the digest below. No remapping needed.
            for i, idea in enumerate(ideas):
                idea["cluster_index"] = i
                idea["source"] = "auto"
            logger.info("Generated %d ideas for user %s", len(ideas), user_id)
        except Exception as e:
            logger.error("Content generation failed for user %s: %s", user_id, e)
            state["errors"] = state.get("errors", []) + [f"content_gen:{user_id}:{e}"]
            continue

        results.append({
            "user_id": user_id,
            "content_profile_id": profile.get("content_profile_id"),
            "ideas": ideas,
            "clusters": clusters,
        })

    state["generated_content"] = results
    return state
