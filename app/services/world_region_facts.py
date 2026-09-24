"""Structured reference facts for the World region page's infobox strip (capital, rough
population, main languages, currency) — deliberately a static table, not a live fetch.

Wikipedia's REST summary API (already used for World script sourcing, see
app/collectors/wikipedia_extracts.py) returns free-text extracts and a lead image, not
structured infobox fields — getting capital/population/currency reliably out of that would
need either Wikidata's SPARQL API (a new, slower dependency for ~36 values that essentially
never change) or scraping the infobox HTML (fragile). Since there are only as many countries
as app.collectors.region_codes.REGION_NAMES already enumerates, and this data is close to
static, a hand-maintained table keyed by the same ISO-2 codes is the simpler, more reliable
choice — same reasoning as REGION_NAMES itself.

Population is a rounded, approximate figure (millions) for display context, not a precise
census number — labeled as such wherever it's shown. Update this table only when a figure is
noticeably stale, not on a schedule.
"""

REGION_FACTS: dict[str, dict] = {
    "US": {"capital": "Washington, D.C.", "population_millions": 341, "languages": ["English"], "currency": "US Dollar", "currency_code": "USD"},
    "GB": {"capital": "London", "population_millions": 68, "languages": ["English"], "currency": "Pound Sterling", "currency_code": "GBP"},
    "FR": {"capital": "Paris", "population_millions": 66, "languages": ["French"], "currency": "Euro", "currency_code": "EUR"},
    "DE": {"capital": "Berlin", "population_millions": 84, "languages": ["German"], "currency": "Euro", "currency_code": "EUR"},
    "IT": {"capital": "Rome", "population_millions": 59, "languages": ["Italian"], "currency": "Euro", "currency_code": "EUR"},
    "ES": {"capital": "Madrid", "population_millions": 48, "languages": ["Spanish"], "currency": "Euro", "currency_code": "EUR"},
    "PT": {"capital": "Lisbon", "population_millions": 10, "languages": ["Portuguese"], "currency": "Euro", "currency_code": "EUR"},
    "CA": {"capital": "Ottawa", "population_millions": 41, "languages": ["English", "French"], "currency": "Canadian Dollar", "currency_code": "CAD"},
    "AU": {"capital": "Canberra", "population_millions": 27, "languages": ["English"], "currency": "Australian Dollar", "currency_code": "AUD"},
    "JP": {"capital": "Tokyo", "population_millions": 123, "languages": ["Japanese"], "currency": "Japanese Yen", "currency_code": "JPY"},
    "KR": {"capital": "Seoul", "population_millions": 52, "languages": ["Korean"], "currency": "South Korean Won", "currency_code": "KRW"},
    "IN": {"capital": "New Delhi", "population_millions": 1441, "languages": ["Hindi", "English"], "currency": "Indian Rupee", "currency_code": "INR"},
    "BR": {"capital": "Brasília", "population_millions": 217, "languages": ["Portuguese"], "currency": "Brazilian Real", "currency_code": "BRL"},
    "TR": {"capital": "Ankara", "population_millions": 86, "languages": ["Turkish"], "currency": "Turkish Lira", "currency_code": "TRY"},
    "SA": {"capital": "Riyadh", "population_millions": 36, "languages": ["Arabic"], "currency": "Saudi Riyal", "currency_code": "SAR"},
    "AE": {"capital": "Abu Dhabi", "population_millions": 10, "languages": ["Arabic"], "currency": "UAE Dirham", "currency_code": "AED"},
    "IL": {"capital": "Jerusalem", "population_millions": 10, "languages": ["Hebrew", "Arabic"], "currency": "Israeli New Shekel", "currency_code": "ILS"},
    "IR": {"capital": "Tehran", "population_millions": 89, "languages": ["Persian"], "currency": "Iranian Rial", "currency_code": "IRR"},
    "NG": {"capital": "Abuja", "population_millions": 224, "languages": ["English"], "currency": "Nigerian Naira", "currency_code": "NGN"},
    "ZA": {"capital": "Pretoria", "population_millions": 60, "languages": ["Zulu", "English", "Afrikaans"], "currency": "South African Rand", "currency_code": "ZAR"},
    "EG": {"capital": "Cairo", "population_millions": 113, "languages": ["Arabic"], "currency": "Egyptian Pound", "currency_code": "EGP"},
    "KE": {"capital": "Nairobi", "population_millions": 55, "languages": ["Swahili", "English"], "currency": "Kenyan Shilling", "currency_code": "KES"},
    "ID": {"capital": "Jakarta", "population_millions": 278, "languages": ["Indonesian"], "currency": "Indonesian Rupiah", "currency_code": "IDR"},
    "PH": {"capital": "Manila", "population_millions": 117, "languages": ["Filipino", "English"], "currency": "Philippine Peso", "currency_code": "PHP"},
    "TH": {"capital": "Bangkok", "population_millions": 71, "languages": ["Thai"], "currency": "Thai Baht", "currency_code": "THB"},
    "VN": {"capital": "Hanoi", "population_millions": 99, "languages": ["Vietnamese"], "currency": "Vietnamese Dong", "currency_code": "VND"},
    "MY": {"capital": "Kuala Lumpur", "population_millions": 34, "languages": ["Malay"], "currency": "Malaysian Ringgit", "currency_code": "MYR"},
    "MX": {"capital": "Mexico City", "population_millions": 129, "languages": ["Spanish"], "currency": "Mexican Peso", "currency_code": "MXN"},
    "AR": {"capital": "Buenos Aires", "population_millions": 46, "languages": ["Spanish"], "currency": "Argentine Peso", "currency_code": "ARS"},
    "CO": {"capital": "Bogotá", "population_millions": 52, "languages": ["Spanish"], "currency": "Colombian Peso", "currency_code": "COP"},
    "CL": {"capital": "Santiago", "population_millions": 20, "languages": ["Spanish"], "currency": "Chilean Peso", "currency_code": "CLP"},
    "PL": {"capital": "Warsaw", "population_millions": 37, "languages": ["Polish"], "currency": "Polish Złoty", "currency_code": "PLN"},
    "UA": {"capital": "Kyiv", "population_millions": 37, "languages": ["Ukrainian"], "currency": "Ukrainian Hryvnia", "currency_code": "UAH"},
    "PK": {"capital": "Islamabad", "population_millions": 241, "languages": ["Urdu", "English"], "currency": "Pakistani Rupee", "currency_code": "PKR"},
    "CN": {"capital": "Beijing", "population_millions": 1410, "languages": ["Mandarin"], "currency": "Renminbi", "currency_code": "CNY"},
    "GR": {"capital": "Athens", "population_millions": 10, "languages": ["Greek"], "currency": "Euro", "currency_code": "EUR"},
}


def flag_emoji(code: str | None) -> str | None:
    """Regional-indicator-symbol flag for an ISO-2 code ("US" -> "🇺🇸"), computed rather
    than stored — works for any valid ISO-2 code, not just the ones in REGION_FACTS."""
    if not code or len(code) != 2 or not code.isalpha():
        return None
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


def region_facts(code: str | None) -> dict | None:
    """REGION_FACTS entry for a region, plus its flag emoji, or None when the region has
    no facts on file (a normal state — not every ISO-2 code in the app has an entry yet)."""
    if not code:
        return None
    facts = REGION_FACTS.get(code.strip().upper())
    if not facts:
        return None
    return {**facts, "flag_emoji": flag_emoji(code)}
