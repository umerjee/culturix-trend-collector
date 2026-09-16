"""Upcoming cultural/religious/political events, for content_strategist.py
to write ideas that anticipate what's coming (a Diwali post two weeks
ahead of Diwali) rather than only react to what's already trending.

Two data sources, per CalendarEvent's own docstring:
- Holidays: auto-synced from Nager Holidays' free public API (no key, no
  rate limit — confirmed live 2026-09-07 against the real endpoint,
  https://nagerholidays.com/api/v4/Holidays/{countryCode}/{year} — NOT the
  legacy date.nager.at domain/v3 schema, which now 301-redirects here with
  a different response shape: date/name/countryCode/nationalHoliday/
  subdivisionCodes/holidayTypes, no more localName/fixed/global/counties).
- Religious observances and political events: hand-curated below. Most
  religious observances run on lunar/lunisolar calendars no holiday API
  computes correctly, and no API tracks political events (elections, etc.)
  at all — this list needs a human to keep it current, ideally reviewed
  every few months. Dates researched live 2026-09-07; lunar-calendar dates
  are moon-sighting-dependent and can shift by a day.
"""
import json
import logging
import os
from datetime import date, datetime, timedelta

logger = logging.getLogger("culturix.services.calendar_events")

# 2026-09-16: this file originally only covered holiday/religious/political
# events -- sports and music (both explicitly requested up front) were never
# added. No single free API covers "upcoming major sports events" and
# "upcoming major music events" across all of TRACKED_REGIONS the way Nager
# does for holidays, and hand-curating them like CURATED_EVENTS would need
# constant manual upkeep for two fast-moving categories. LLM-generated
# instead, refreshed periodically (see _sports_music_needs_refresh) rather
# than on every daily sync, since this costs real API calls and day-to-day
# churn in "what sports/music events are coming up" is low.
#
# Same failure mode as trend_validator.py's pre-2026-09-16 bug applies here
# if not careful: an LLM has a training cutoff and no web access, so asking
# it to invent SPECIFIC one-off claims (a particular unannounced album drop
# date) would just produce fabrications with false confidence. The prompt
# below is scoped to well-established, calendar-fixed recurring events
# (major championships/tournaments/award shows that happen on a known
# annual cycle) rather than speculative one-off announcements, for exactly
# that reason.
_SPORTS_MUSIC_REFRESH_INTERVAL_DAYS = 7


def _call_calendar_llm(prompt: str) -> str:
    """Same DeepSeek-primary/Claude-Haiku-fallback resilience pattern as
    trend_validator.py's _call_validation_llm — kept as its own copy since
    each pipeline/service module here owns its LLM call helper rather than
    sharing one across unrelated concerns."""
    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("DeepSeek calendar-generation call failed, falling back to Claude: %s", e)

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _parse_json_array(raw: str) -> list:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())

# Same canonical region vocabulary as app/collectors/region_codes.py,
# matching the countries the trend collectors already track — so an
# upcoming event only ever gets surfaced for an audience we actually
# collect trends for.
TRACKED_REGIONS = ["US", "GB", "IN", "JP", "KR", "FR", "DE", "BR", "CA", "AU", "CN", "IT", "ES", "PT"]

_NAGER_API_BASE = "https://nagerholidays.com/api/v4/Holidays"

# Hand-curated — see module docstring. `regions` is the diaspora-aware
# audience this event is actually relevant to, not just the country of
# origin (e.g. Diwali matters to US/GB/CA/AU content too, not only India).
# Only forward-looking entries from this file's own research date
# (2026-09-07) onward are kept here; don't add past dates.
CURATED_EVENTS = [
    # India is a TRACKED_REGIONS entry but confirmed live 2026-09-07 to
    # return HTTP 204 (no data, not a wrong country code) from Nager's
    # holiday API for every year tried — genuinely unsupported, not a bug
    # in sync_holidays(). These fixed-date national holidays fill that gap
    # by hand; unlike the religious entries below they don't depend on a
    # lunar calendar, so the dates are exact, not moon-sighting-dependent.
    {
        "name": "Gandhi Jayanti", "category": "holiday", "date": date(2026, 10, 2),
        "regions": ["IN"], "description": "National holiday marking Gandhi's birthday.",
    },
    {
        "name": "Republic Day", "category": "holiday", "date": date(2027, 1, 26),
        "regions": ["IN"], "description": "India's national day marking its constitution taking effect.",
    },
    {
        "name": "Independence Day (India)", "category": "holiday", "date": date(2027, 8, 15),
        "regions": ["IN"], "description": "Marks independence from British rule in 1947.",
    },
    {
        "name": "Diwali", "category": "religious", "date": date(2026, 11, 8),
        "regions": ["IN", "US", "GB", "CA", "AU"],
        "description": "Hindu/Sikh/Jain festival of lights, 5-day celebration Nov 6-10 2026.",
    },
    {
        "name": "Hanukkah (begins)", "category": "religious", "date": date(2026, 12, 5),
        "regions": ["US", "GB", "FR", "CA"],
        "description": "Jewish festival of lights, 8 days from sundown Dec 5 through Dec 12 2026.",
    },
    {
        "name": "Lunar New Year", "category": "religious", "date": date(2027, 2, 6),
        "regions": ["CN", "KR", "US", "CA", "AU"],
        "description": "Chinese/Korean New Year (Year of the Horse).",
    },
    {
        "name": "Eid al-Fitr", "category": "religious", "date": date(2027, 3, 8),
        "regions": ["IN", "GB", "FR", "DE", "US"],
        "description": "Marks the end of Ramadan. Date is moon-sighting-dependent, may shift by a day.",
    },
    {
        "name": "France Senate election", "category": "political", "date": date(2026, 9, 27),
        "regions": ["FR"],
        "description": "Indirect election for Series 2 Senate seats.",
    },
    {
        "name": "Brazil general election", "category": "political", "date": date(2026, 10, 4),
        "regions": ["BR"],
        "description": "Presidential, Chamber of Deputies and Senate elections.",
    },
    {
        "name": "US midterm elections", "category": "political", "date": date(2026, 11, 3),
        "regions": ["US"],
        "description": "House of Representatives and one-third of the Senate.",
    },
]


def sync_holidays(session, years: list = None) -> int:
    """Fetches national holidays for TRACKED_REGIONS from the Nager API and
    upserts them (source="api:nager") — safe to re-run, keyed on the
    model's (name, date) unique constraint. Returns the count of rows
    written. Skips a region/year on any request failure rather than
    aborting the whole sync — one flaky country shouldn't block the rest,
    same posture as app/collectors/orchestrator.py's per-collector
    isolation."""
    import httpx
    from app.models.calendar_event import CalendarEvent

    if years is None:
        this_year = date.today().year
        years = [this_year, this_year + 1]

    written = 0
    for region in TRACKED_REGIONS:
        for year in years:
            try:
                resp = httpx.get(f"{_NAGER_API_BASE}/{region}/{year}", timeout=15)
                resp.raise_for_status()
                holidays = resp.json()
            except Exception:
                logger.warning("Holiday sync failed for %s/%d — skipping", region, year, exc_info=True)
                continue
            # The API can list the SAME (name, date) more than once in one
            # response — different subdivisions observe it differently (e.g.
            # two "Good Friday" 2026-04-03 entries for US, one public in most
            # states, one optional in Texas). We don't track subdivision-level
            # granularity (`regions` is country-level only), so collapse to
            # ONE row per (name, date) — an in-memory guard, not another DB
            # query, since a same-batch duplicate isn't committed yet for a
            # query to see.
            seen_this_batch = set()
            for h in holidays:
                try:
                    event_date = date.fromisoformat(h["date"])
                except (KeyError, ValueError):
                    continue
                name = h.get("name", "")[:200]
                if (name, event_date) in seen_this_batch:
                    continue
                seen_this_batch.add((name, event_date))
                existing = session.query(CalendarEvent).filter_by(name=name, date=event_date).first()
                if existing:
                    if existing.source == "api:nager" and region not in (existing.regions or []):
                        existing.regions = list(set((existing.regions or []) + [region]))
                    continue
                session.add(CalendarEvent(
                    name=name, category="holiday", date=event_date,
                    regions=[region], description=None, source="api:nager",
                ))
                written += 1
        session.commit()
    logger.info("Holiday sync wrote %d new rows across %s", written, years)
    return written


def seed_curated_events(session) -> int:
    """Upserts CURATED_EVENTS — safe to re-run on every deploy/startup,
    same idempotent posture as app/main.py's schema bootstrap. Updates
    regions/description on an existing row rather than skipping, so
    editing this list and redeploying actually takes effect."""
    from app.models.calendar_event import CalendarEvent

    written = 0
    for event in CURATED_EVENTS:
        existing = session.query(CalendarEvent).filter_by(name=event["name"], date=event["date"]).first()
        if existing:
            existing.regions = event["regions"]
            existing.description = event["description"]
            existing.category = event["category"]
            continue
        session.add(CalendarEvent(
            name=event["name"], category=event["category"], date=event["date"],
            regions=event["regions"], description=event["description"], source="curated",
        ))
        written += 1
    session.commit()
    logger.info("Curated event seed wrote %d new rows", written)
    return written


def _sports_music_needs_refresh(session) -> bool:
    from app.models.calendar_event import CalendarEvent

    latest = (
        session.query(CalendarEvent.created_at)
        .filter(CalendarEvent.source == "llm_generated")
        .order_by(CalendarEvent.created_at.desc())
        .first()
    )
    if latest is None or latest[0] is None:
        return True
    age_days = (datetime.utcnow() - latest[0]).total_seconds() / 86400.0
    return age_days >= _SPORTS_MUSIC_REFRESH_INTERVAL_DAYS


def generate_sports_and_music_events(session, lookahead_days: int = 120) -> int:
    """LLM-generated upcoming sports/music events, upserted the same way as
    seed_curated_events (keyed on (name, date), safe to re-run). Skips the
    LLM call entirely if a batch was already generated within
    _SPORTS_MUSIC_REFRESH_INTERVAL_DAYS -- see module docstring for why this
    is periodic rather than run on every daily sync."""
    from app.models.calendar_event import CalendarEvent

    if not _sports_music_needs_refresh(session):
        logger.info("Sports/music events generated within the last %d days — skipping", _SPORTS_MUSIC_REFRESH_INTERVAL_DAYS)
        return 0

    today = date.today()
    horizon = today + timedelta(days=lookahead_days)
    prompt = f"""List notable upcoming SPORTS and MUSIC events between {today.isoformat()} and {horizon.isoformat()}, relevant to a social-media content-intelligence platform tracking these countries: {", ".join(TRACKED_REGIONS)}.

Consider ALL of these sub-areas before answering, and include every one where you have a high-confidence, calendar-fixed date in this window — don't stop after the first few obvious ones: major football/soccer (Premier League, Champions League, La Liga, Bundesliga, Serie A — openers, finals, or notable fixture dates), American football (NFL), basketball (NBA), baseball (MLB), cricket (IPL, international series), tennis Grand Slams, Formula 1 races, major boxing/UFC cards, the Olympics/World Cup only if genuinely within this window; and for music: major annual award shows (Grammys, VMAs, Billboard Music Awards, BRIT Awards, etc.), well-known recurring festivals with fixed annual dates (Coachella, Glastonbury, etc.).

Only include events you have HIGH confidence actually occur on a known, calendar-fixed annual/recurring cycle. Do NOT invent or guess at specific one-off announcements you aren't confident about (a particular unannounced album release date, an unconfirmed tour date) — if you're not sure of the exact date, either omit it or use your best-known recurring date for that annual event; do not fabricate specifics to seem more complete. Aim for a thorough list (10-20 events) covering as many of the above sub-areas as you can respond to with genuine confidence, not just one or two.

For EACH event, provide:
- name: short, specific event name
- category: "sports" or "music"
- date: EXACTLY ONE date, YYYY-MM-DD — never a range or "X to Y". If the event is a season/tournament that spans multiple days or weeks (a league season, a multi-week tournament), pick the SINGLE most newsworthy day within this window to represent it (the opening day, or the final/championship day, or the awards-ceremony date) — not the whole span.
- regions: array of ISO country codes from the list above this event is relevant to (diaspora/fandom-aware, not just country of origin)
- description: one sentence

Return ONLY a JSON array of objects with exactly these keys: name, category, date, regions, description. Every "date" value MUST be a single YYYY-MM-DD string, and MUST fall within {today.isoformat()} and {horizon.isoformat()} inclusive. Return an empty array if you have no high-confidence events to report — do not pad with speculative ones."""

    try:
        events = _parse_json_array(_call_calendar_llm(prompt))
    except Exception as e:
        logger.warning("Sports/music event generation failed — skipping this cycle: %s", e)
        return 0

    written = 0
    for event in events:
        try:
            name = str(event["name"])[:200]
            category = event.get("category") if event.get("category") in ("sports", "music") else "sports"
            event_date = date.fromisoformat(event["date"])
        except (KeyError, ValueError, TypeError):
            logger.warning("Skipping malformed LLM-generated event: %r", event)
            continue
        if not (today <= event_date <= horizon):
            continue  # LLM occasionally drifts outside the requested window
        regions = [r for r in (event.get("regions") or []) if r in TRACKED_REGIONS]
        description = event.get("description")

        existing = session.query(CalendarEvent).filter_by(name=name, date=event_date).first()
        if existing:
            existing.regions = regions
            existing.description = description
            existing.category = category
            existing.source = "llm_generated"
            continue
        session.add(CalendarEvent(
            name=name, category=category, date=event_date,
            regions=regions, description=description, source="llm_generated",
        ))
        written += 1
    session.commit()
    logger.info("Sports/music event generation wrote %d new rows", written)
    return written


def get_upcoming_events(session, lookahead_days: int = 45, regions: list = None) -> list:
    """Events between today and lookahead_days from now, soonest first.
    `regions` filters to events relevant to ANY of the given codes (or
    events with no region tag at all, i.e. globally relevant) — pass None
    for every tracked region. A ContentProfile has no single "region" of
    its own today (see app/pipeline/nodes/calendar_context.py), so the
    normal caller passes None and lets the LLM decide which upcoming
    events are actually relevant to a given niche/audience."""
    from app.models.calendar_event import CalendarEvent
    from sqlalchemy import or_

    today = date.today()
    horizon = today + timedelta(days=lookahead_days)
    query = session.query(CalendarEvent).filter(
        CalendarEvent.date >= today, CalendarEvent.date <= horizon,
    )
    if regions:
        # ARRAY overlap: event.regions has at least one code in common with
        # `regions`, OR event.regions is null/empty (globally relevant).
        query = query.filter(or_(
            CalendarEvent.regions.overlap(regions),
            CalendarEvent.regions.is_(None),
        ))
    return query.order_by(CalendarEvent.date.asc()).all()
