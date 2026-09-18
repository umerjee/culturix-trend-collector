"""Canonicalizes the region values collectors use to fetch data into one
consistent vocabulary before they're stored on Trend.region.

Different collectors use different conventions today: tiktok.py/youtube.py use
ISO-2-letter codes ("US", "GB", "IN"), twitter.py's proxy fallback uses
lowercase names ("us", "uk", "india", "japan", "global"). Without normalizing these to
one canonical form, persona_mapper.py's region filter would have to know
about every collector's private vocabulary instead of comparing against one
set of codes.
"""
_ALIASES = {
    "uk": "GB",
    "india": "IN",
    "japan": "JP",
    "global": None,  # no single region — genuinely unknown, not a real code
    "us": "US",
    # Added so Twitter's proxy fallback (app/collectors/twitter.py's
    # TWITTER_REGIONS) can tag these — previously only "us"/"uk"/"india"/
    # "japan" were resolvable, leaving Twitter (the single largest collector
    # by volume) unable to ever tag FR/CA/AU even though those are offered
    # as target_regions picker options and TikTok/YouTube do tag them —
    # a profile targeting e.g. France-only could get zero clusters on any
    # day where the top clusters happened to carry a resolved-but-non-FR
    # region from Twitter-sourced posts instead of staying unknown.
    "france": "FR",
    "canada": "CA",
    "australia": "AU",
    "italy": "IT",
    "spain": "ES",
    "portugal": "PT",
}


# Shared target region list every collector's own *_REGIONS constant draws
# from (see tiktok.py/youtube.py/google_trends.py/twitter.py) — added
# 2026-09-18 after a DB audit found real coverage was only 13 countries
# (Western/wealthy-skewed) and 28% of all trend rows had no region at all,
# blocking World Features (see app/services/culturetoon_script.py::
# generate_world_script) from having real grounding for most of the world.
# Not every platform supports every one of these — each collector prunes
# this list down to what's actually confirmed live for it (see each
# collector's own *_REGIONS definition and comments).
#
# RU deliberately excluded: X/Twitter and most Western platforms this repo
# collects from are blocked/degraded there, so calls would silently fail.
SHARED_TARGET_REGIONS = [
    # Existing 13 (already covered before this list existed)
    "US", "GB", "FR", "DE", "IT", "ES", "PT", "CA", "AU", "JP", "KR", "IN", "BR",
    # Middle East — IR added 2026-09-18, a real gap: the first-ever World
    # Feature (the Strait of Hormuz) is about Iran, and Iran was missing
    # from this list entirely, leaving that flagship content with zero real
    # trend grounding behind it. Live-verified across YouTube/Google
    # Trends/TikTok/the Twitter proxy before trusting it (see this list's
    # own "not every platform supports every one of these" note above).
    "TR", "SA", "AE", "IL", "IR",
    # Africa
    "NG", "ZA", "EG", "KE",
    # Southeast Asia
    "ID", "PH", "TH", "VN", "MY",
    # Latin America beyond Brazil
    "MX", "AR", "CO", "CL",
    # Eastern Europe
    "PL", "UA",
    # Extra Asia
    "PK", "CN",
]


def normalize_region(raw: str | None) -> str | None:
    """Canonical form is an uppercase ISO-2-ish code (US, GB, IN, JP, KR, FR,
    DE, BR, CA, AU, CN) or None for platforms/fetches with no regional concept."""
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    stripped = raw.strip()
    return stripped.upper() if len(stripped) <= 3 else None


REGION_NAMES = {
    "US": "the United States", "GB": "the United Kingdom", "FR": "France", "DE": "Germany",
    "IT": "Italy", "ES": "Spain", "PT": "Portugal", "CA": "Canada", "AU": "Australia",
    "JP": "Japan", "KR": "South Korea", "IN": "India", "BR": "Brazil", "TR": "Turkey",
    "SA": "Saudi Arabia", "AE": "the UAE", "IL": "Israel", "IR": "Iran", "NG": "Nigeria",
    "ZA": "South Africa", "EG": "Egypt", "KE": "Kenya", "ID": "Indonesia", "PH": "the Philippines",
    "TH": "Thailand", "VN": "Vietnam", "MY": "Malaysia", "MX": "Mexico", "AR": "Argentina",
    "CO": "Colombia", "CL": "Chile", "PL": "Poland", "UA": "Ukraine", "PK": "Pakistan",
    "CN": "China", "GR": "Greece",
}


def region_name(code: str | None) -> str:
    """Human-readable region label for prompts and UI; falls back to the bare
    code (or "the world" for a region-less subject) rather than raising."""
    if not code:
        return "the world"
    return REGION_NAMES.get(code.strip().upper(), code.strip().upper())
