"""Period accuracy for World videos: which era a video is set in, what belongs in it, and what does not.

Why this exists: a render of "the rise of the Roman Empire" (753 BC to 27 BC) showed jeeps at the huts, a
khaki military camp, asphalt streets with vans and steamships. Three causes, all ours:
- the video prompt never said when the video is set (the era appeared once, inside the "premise" sentence);
- the renderer's own motion boilerplate asked the model to keep "vehicles" moving;
- nothing checked a script or a prompt for objects that did not exist yet.

So an era is now decided ONCE per video (or given by the curator), stored with the script, and used three ways:
1. the writer is told to show only what existed then, and a deterministic check flags anachronistic words in
   every visual (one rewrite), so a modern object cannot survive on the LLM's good behaviour alone;
2. every video segment's prompt opens with the era and a description of what that period looked like
   (positive wording: telling an image/video model what NOT to draw inside the prompt measured worst);
3. the negative prompt lists the modern things to avoid, which is what a negative prompt is for.

An era with an end year of 1900 or later is left alone: vehicles, aircraft and electricity are legitimate there.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger("culturix.services.world_era")

MODERN_FROM_YEAR = 1900
MIN_YEAR, MAX_YEAR = -10000, 2100


class EraError(ValueError):
    """The curator's period text could not be understood."""


_BC = r"(?:BC|BCE|B\.C\.|B\.C\.E\.)"
_AD = r"(?:AD|CE|A\.D\.|C\.E\.)"
_YEAR_BC_AD = re.compile(rf"\b(\d{{1,4}})\s*({_BC}|{_AD})(?![A-Za-z])", re.IGNORECASE)
_YEAR_AD_FIRST = re.compile(rf"\b({_AD})\s*(\d{{1,4}})\b", re.IGNORECASE)
_YEAR_PLAIN = re.compile(r"\b(?:in|by|since|until|from|circa|c\.|of|to|and)\s+(1[0-9]{3}|20[0-2][0-9])\b", re.IGNORECASE)
_YEAR_BARE = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9])\b")
_PRESENT = re.compile(r"\b(present|today|modern|contemporary|current)\b", re.IGNORECASE)
PRESENT_YEAR = 2020


def parse_years(text: str, allow_bare: bool = False) -> list[int]:
    """Every year a piece of text names, as integers with BC negative ("753 BC" -> -753). A plain
    four-digit number only counts after a word like "in" or "by", so "1200 soldiers" is not a year.
    allow_bare also accepts a lone year ("Normandy, June 1944"): for text a person typed as a period,
    where a number cannot be a count."""
    years = []
    for match in _YEAR_BC_AD.finditer(text or ""):
        value, era = int(match.group(1)), match.group(2).upper().replace(".", "")
        years.append(-value if era.startswith("B") else value)
    for match in _YEAR_AD_FIRST.finditer(text or ""):
        years.append(int(match.group(2)))
    years += [int(m.group(1)) for m in _YEAR_PLAIN.finditer(text or "")]
    if allow_bare:
        years += [int(m.group(1)) for m in _YEAR_BARE.finditer(text or "")]
    return sorted({y for y in years if MIN_YEAR <= y <= MAX_YEAR}) if allow_bare else \
        [y for y in years if MIN_YEAR <= y <= MAX_YEAR]


def year_text(year: int) -> str:
    return f"{-year} BC" if year < 0 else f"{year} AD" if year < 1000 else str(year)


# ---- what each period looked like, and what did not exist yet ---------------------------------------

_MODERN_TECH = (
    "car|cars|automobile|automobiles|truck|trucks|lorry|lorries|jeep|jeeps|bus|buses|motorcycle|motorcycles|"
    "motorbike|motorbikes|tractor|tractors|bulldozer|bulldozers|airplane|airplanes|aeroplane|aeroplanes|aircraft|"
    "helicopter|helicopters|drone|drones|motorboat|motorboats|speedboat|speedboats|electric|electricity|"
    "light bulb|light bulbs|lamp post|lamp posts|street lamp|street lamps|streetlight|streetlights|neon|"
    "power line|power lines|telephone|television|radio|antenna|satellite|skyscraper|skyscrapers|asphalt|"
    "tarmac|highway|highways|billboard|billboards|traffic|khaki|jeans|t-shirt|t-shirts|machine gun|machine guns|"
    "modern|contemporary|steel bridge|concrete highway"
)
_INDUSTRY = (
    "railway|railways|railroad|railroads|locomotive|locomotives|steam engine|steam engines|steamship|steamships|"
    "steamer|steamers|steam-powered|factory|factories|smokestack|smokestacks"
)
_NO_CHIMNEYS = "chimney|chimneys"
_FIREARMS = (
    "gun|guns|rifle|rifles|musket|muskets|cannon|cannons|pistol|pistols|gunpowder|artillery|grenade|grenades|"
    "firearm|firearms|bullet|bullets"
)

_PERIOD_NEGATIVE_COMMON = (
    "cars, trucks, jeeps, motor vehicles, motorboats, steamships, aircraft, helicopters, asphalt roads, power "
    "lines, street lamps, electric lights, factories, smokestacks, skyscrapers, modern buildings, sash windows, "
    "khaki and olive-drab uniforms, canvas army tents, modern clothing, road signs, billboards, aerial view of a "
    "modern city, modern town, suburban houses, uniform tiled roofs, window shutters, satellite dishes, street "
    "markings, shop signs, parked cars"
)

ERA_BANDS = [
    {
        "name": "ancient", "until": 500,
        "look": "the ancient world: buildings of timber, mud brick, rough stone and terracotta tile; people in "
                "woven wool and linen tunics, cloaks and sandals; bronze and iron tools and weapons; oil lamps "
                "and torches; ox carts, horses, and oared and sailing ships",
        "forbidden": "|".join([_MODERN_TECH, _INDUSTRY, _NO_CHIMNEYS, _FIREARMS]),
        "negative": _PERIOD_NEGATIVE_COMMON + ", chimneys, guns, rifles, cannons",
    },
    {
        "name": "medieval", "until": 1500,
        "look": "the medieval world: timber-framed and rough stone buildings with thatch, slate or tile roofs; "
                "people in wool, linen and leather clothing; swords, spears, shields and bows; horse and ox "
                "carts; sailing ships",
        "forbidden": "|".join([_MODERN_TECH, _INDUSTRY]),
        "negative": _PERIOD_NEGATIVE_COMMON,
    },
    {
        "name": "early_modern", "until": 1800,
        "look": "the age of sail: brick, stone and timber buildings with tile roofs; people in period wool, "
                "linen and leather clothing with tricorn hats and long coats; muskets and cannons; horse-drawn "
                "carriages and wagons; wooden sailing ships",
        "forbidden": "|".join([_MODERN_TECH, _INDUSTRY]),
        "negative": _PERIOD_NEGATIVE_COMMON,
    },
    {
        "name": "industrial", "until": MODERN_FROM_YEAR,
        "look": "the 19th century: brick and stone buildings, gas lamps, cobbled streets; people in period "
                "coats, dresses and hats; horse-drawn carriages, steam engines and early railways; iron and "
                "wooden ships with sails and steam",
        "forbidden": _MODERN_TECH,
        "negative": "cars, trucks, motor vehicles, aircraft, electric lights, power lines, asphalt roads, "
                    "skyscrapers, modern buildings, modern clothing, road signs, billboards",
    },
]

_BAND_PATTERNS = {b["name"]: re.compile(r"\b(" + b["forbidden"] + r")\b", re.IGNORECASE) for b in ERA_BANDS}


def band_for(era: Optional[dict]) -> Optional[dict]:
    """The period description for an era, or None when the era is modern (1900+) or unknown."""
    if not era or era.get("end_year") is None or era["end_year"] >= MODERN_FROM_YEAR:
        return None
    for band in ERA_BANDS:
        if era["end_year"] < band["until"]:
            return band
    return None


def era_prompt_line(era: Optional[dict], phase: Optional[dict] = None, year: Optional[int] = None) -> str:
    """The sentence every video segment opens with. Positive wording only. With a `phase` (what the place looked
    like at that time, see period_phases) the description is specific to the place and year; without one it is
    the generic description of the whole era (which, for 753 BC, produced marble columns and multi-storey stone
    streets: the model's idea of "ancient")."""
    if not era or not era.get("label"):
        return ""
    label = era["label"].strip().rstrip(".")
    if phase and phase.get("look"):
        when = f" ({year_text(year)})" if year is not None else ""
        return f"{label}. {phase['label']}{when}: {phase['look'].strip().rstrip('.')}. Everything on screen belongs to this period."
    band = band_for(era)
    if band:
        return f"{label}. Set in {band['look']}. Everything on screen belongs to this period."
    return f"{label}. Everything on screen belongs to this time and place."


def era_negative_terms(era: Optional[dict], phase: Optional[dict] = None) -> str:
    band = band_for(era)
    parts = [band["negative"]] if band else []
    if band and phase and phase.get("avoid"):
        parts.append(", ".join(phase["avoid"]))
    return ", ".join(parts)


def find_anachronisms(text: str, era: Optional[dict], phase: Optional[dict] = None) -> list[str]:
    """Distinct words in `text` naming something that did not exist in the era, or in this phase of it
    ([] for a modern era)."""
    band = band_for(era)
    if not band or not text:
        return []
    found = []
    for match in _BAND_PATTERNS[band["name"]].finditer(text):
        word = match.group(0).lower()
        if word not in found:
            found.append(word)
    for term in (phase or {}).get("avoid") or []:
        if term.lower() not in found and re.search(rf"\b{re.escape(term)}(?:s|es)?\b", text, re.IGNORECASE):
            found.append(term.lower())
    return found


def check_world_anachronisms(shots: Optional[list], era: Optional[dict]) -> list[str]:
    """One problem per subject shot whose visual or location names something that did not exist in the era, or
    in the phase of it the shot's own year falls in."""
    if not band_for(era):
        return []
    problems = []
    phases = shot_phases(shots, era)
    for shot, (phase, year) in zip(shots or [], phases):
        text = " ".join(str(shot.get(k) or "") for k in ("subject_visual", "visual", "location", "action"))
        words = find_anachronisms(text, era, phase)
        if words:
            where = f"{phase['label']} ({year_text(year)})" if phase and year is not None else era["label"]
            problems.append(
                f"Shot {shot.get('shot_number')}: {', '.join(repr(w) for w in words)} did not exist in "
                f"{where}. Remove it and show only things that existed then."
            )
    return problems


# ---- phases: what the place looked like when -------------------------------------------------------

MAX_PHASES = 4


def phase_for_year(era: Optional[dict], year: Optional[int]) -> Optional[dict]:
    """The phase of the era that contains `year` (the nearest one if it falls in a gap), or None."""
    phases = (era or {}).get("phases") or []
    if not phases or year is None:
        return phases[0] if phases and year is None else None
    for phase in phases:
        if phase["from_year"] <= year <= phase["to_year"]:
            return phase
    return min(phases, key=lambda ph: min(abs(year - ph["from_year"]), abs(year - ph["to_year"])))


def shot_years(shots: Optional[list], era: Optional[dict]) -> list[Optional[int]]:
    """The year each shot depicts: the year its own narration names, else the year the writer gave it, else the
    previous shot's, else the start of the era. Narration wins because that is what the viewer is told."""
    years, previous = [], None
    for shot in shots or []:
        named = parse_years(shot.get("dialogue") or "")
        given = shot.get("year")
        year = named[0] if named else (int(given) if isinstance(given, (int, float)) and not isinstance(given, bool)
                                       and MIN_YEAR <= given <= MAX_YEAR else previous)
        if year is None and era:
            year = era.get("start_year")
        years.append(year)
        previous = year
    return years


def shot_phases(shots: Optional[list], era: Optional[dict]) -> list[tuple]:
    """[(phase or None, year or None)] per shot."""
    return [(phase_for_year(era, year), year) for year in shot_years(shots, era)]


def assign_shot_periods(shots: Optional[list], era: Optional[dict]) -> list:
    """Copies of the shots with `period_year` and `period_phase` (the phase's index) set, which is what the
    renderer reads to describe each shot's own time and place. Unchanged copies when the era has no phases."""
    out = []
    phases = (era or {}).get("phases") or []
    for shot, (phase, year) in zip(shots or [], shot_phases(shots, era)):
        shot = dict(shot)
        if phases and phase is not None:
            shot["period_year"] = year
            shot["period_phase"] = phases.index(phase)
        out.append(shot)
    return out


def _clean_phases(raw, start: int, end: int) -> list[dict]:
    phases = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        span = _valid(item.get("from_year"), item.get("to_year"))
        look, label = str(item.get("look") or "").strip(), str(item.get("label") or "").strip()
        if not span or not look or not label:
            continue
        avoid = []
        for term in item.get("avoid") or []:
            term = str(term).strip().lower()
            if 2 <= len(term) <= 30 and term not in avoid:
                avoid.append(term)
        phases.append({"from_year": span[0], "to_year": span[1], "label": label[:60], "look": look[:420], "avoid": avoid[:10]})
    return sorted(phases, key=lambda ph: ph["from_year"])[:MAX_PHASES]


def period_phases(label: str, start: int, end: int, title: str, source_facts: str) -> list[dict]:
    """Ask the model what the place looked like in each phase of the story: what buildings were made of and how
    big they were, roofs, streets, clothing, tools, transport, plus the things that did not exist yet there. []
    if it cannot be decided. This is what makes 753 BC Rome a village of thatched wattle-and-daub huts instead of
    the generic "ancient world" of marble columns and stone streets that the model draws otherwise."""
    from app.services.culturetoon_script import ToonScriptGenerationError, _call_llm_json

    prompt = f"""Describe what this place looked like in each phase of the story, so a video shows only what existed then.

Subject: {title}
Place and period: {label} ({year_text(start)} to {year_text(end)})
Source material: {(source_facts or '').strip()[:1200]}

Return ONLY valid JSON: {{"phases": [{{"from_year": integer, "to_year": integer, "label": string, "look": string, "avoid": [string]}}]}}
- 1 to {MAX_PHASES} phases, in time order, together covering {start} to {end} (BC years are negative integers). Use one phase if the period looked the same throughout.
- label: a few words naming the phase.
- look: 35 to 55 words, concrete and visual, written for a video model. It must state: what the buildings were made of, the tallest they got (in storeys) and their size, the roofs, the street layout and surface, the colour and weathering of the materials, what people wore, the tools, animals and transport, and the landscape. Describe a low, irregular, weathered place, never a tidy modern town: a video model given a vague "stone buildings with tiled roofs" draws a present-day Italian town with shutters and paved grids. Describe only what WAS there, in positive terms, exact for THIS place and time, not a generic "ancient" or "medieval" look.
- avoid: up to 10 single words or two-word terms for things you are CERTAIN did not yet exist in that phase in that place and that a video model might wrongly draw (kinds of building, materials, structures, clothing, vehicles, technology). If you are not certain something was absent, leave it out: a wrong entry forbids something that really was there."""
    try:
        parsed = _call_llm_json(prompt, temperature=0.1, max_tokens=900)
    except ToonScriptGenerationError as exc:
        logger.warning("Could not describe the phases of %r: %s", label, exc)
        return []
    return _clean_phases(parsed.get("phases"), start, end)


def attach_phases(era: Optional[dict], title: str, source_facts: str) -> Optional[dict]:
    """The era with its phases, worked out if it has none yet. A modern era needs none; a failure leaves the era
    as it was (the generic description of its band still applies)."""
    if not era or not band_for(era) or era.get("phases"):
        return era
    phases = period_phases(era["label"], era["start_year"], era["end_year"], title, source_facts)
    return {**era, "phases": phases} if phases else era


# ---- deciding the era ---------------------------------------------------------------------------------

def _valid(start, end) -> Optional[tuple]:
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        return None
    if not (MIN_YEAR <= start <= MAX_YEAR and MIN_YEAR <= end <= MAX_YEAR):
        return None
    return (start, end) if start <= end else (end, start)


def era_from_text(text: str) -> dict:
    """An era from a curator's own words, e.g. "Roman Republic, 307 BC to 27 BC". The label is exactly what
    they typed; the years are read from it. Raises EraError if it names no year, since the era's end year is
    what decides which objects are allowed."""
    text = (text or "").strip()
    years = parse_years(text, allow_bare=True)
    if text and not years and _PRESENT.search(text):
        years = [PRESENT_YEAR]          # "Present day": a modern period, so no period guard applies
    if not text or not years:
        raise EraError('Include at least one year, for example "Roman Republic, 307 BC" or "Normandy, 1944".')
    return {"label": text[:120], "start_year": min(years), "end_year": max(years), "source": "curator"}


def widen_to_narration(era: Optional[dict], shots: Optional[list]) -> Optional[dict]:
    """The era, widened to include every year the narration itself names. A script that says "in 27 BC" is
    not set before that."""
    if not era:
        return era
    years = []
    for shot in shots or []:
        years += parse_years(shot.get("dialogue") or "")
    if not years:
        return era
    return {**era, "start_year": min(era["start_year"], min(years)), "end_year": max(era["end_year"], max(years))}


def determine_world_era(title: str, source_facts: str) -> Optional[dict]:
    """Ask the model which period the video's story covers, then sanity-check the answer against years the
    source and title actually name. None if it cannot be decided (the era guard is then off, and the
    reviewer says so). A present-day subject gets the present as its era, which turns the guard off."""
    from app.services.culturetoon_script import ToonScriptGenerationError, _call_llm_json

    prompt = f"""Which historical period does a short video about this subject show?

Subject: {title}
Source material: {(source_facts or '').strip()[:1500]}

Return ONLY valid JSON: {{"label": string, "start_year": integer, "end_year": integer}}
- label: the place and period in a few words, e.g. "Ancient Rome, 753 BC to 27 BC" or "Normandy, June 1944".
- Years are integers and BC years are negative (753 BC is -753).
- start_year is the earliest time the video shows and end_year the LATEST time it shows.
- If the subject is a place, natural feature or phenomenon with no historical story, or it is about the present
  day, use start_year 2020 and end_year 2020 with the label "Present day"."""
    try:
        parsed = _call_llm_json(prompt, temperature=0.1, max_tokens=200)
    except ToonScriptGenerationError as exc:
        logger.warning("Could not determine the era for %r: %s", title, exc)
        return None
    span = _valid(parsed.get("start_year"), parsed.get("end_year"))
    label = str(parsed.get("label") or "").strip()
    if not span or not label:
        return None
    start, end = span
    # A story about 1944 must not be dated to the Bronze Age because the model guessed: if the title or the
    # opening of the source names years, the era must reach them.
    named = parse_years(f"{title}. {(source_facts or '')[:600]}")
    if named and (end < min(named) - 1 or start > max(named) + 1):
        logger.warning("Era %s-%s for %r disagrees with the years the source names %s; using those",
                       start, end, title, named)
        start, end = min(named), max(named)
        label = f"{label.split(',')[0].strip()}, {year_text(start)}" + (f" to {year_text(end)}" if end != start else "")
    # The prompt asks the model to write the year into the label itself, but it doesn't always —
    # confirmed live: a UNESCO subject spanning centuries ("Byzantine to Ottoman") came back with a
    # correctly-computed start_year/end_year but a label with no digits in it at all. This label is
    # what a curator sees pre-filled in the "Period shown" field and what era_from_text() re-parses
    # on submit — era_from_text has no access to start_year/end_year, only the label text, so a
    # label with no parseable year makes the curator hit "Include at least one year" on an AI
    # suggestion that already knew the year internally. Guarantee the label always parses, the same
    # way the disagreement-correction above already does.
    if not parse_years(label, allow_bare=True):
        label = f"{label}, {year_text(start)}" + (f" to {year_text(end)}" if end != start else "")
    return {"label": label[:120], "start_year": start, "end_year": end, "source": "ai"}
