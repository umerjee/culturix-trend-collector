"""Languages the platform will translate into, and how to name them to each
engine. Google (via deep_translator 1.9.1) supports 133 languages; this is the
set we expose (UI pickers, API validation). Adding a language is one line here.

Canonical codes are ISO 639-1, plus zh-CN / zh-TW. Engines may spell a code
differently: Google still calls Hebrew "iw" (sending "he" fails with "No support
for the provided language" — verified live), so each engine gets its own code
through engine_code()."""

# canonical code -> English name
LANGUAGES: dict[str, str] = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian",
    "tr": "Turkish", "ar": "Arabic", "he": "Hebrew", "fa": "Persian", "hi": "Hindi",
    "ur": "Urdu", "bn": "Bengali", "id": "Indonesian", "ms": "Malay", "th": "Thai",
    "vi": "Vietnamese", "ja": "Japanese", "ko": "Korean", "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)", "sw": "Swahili", "el": "Greek", "cs": "Czech",
    "ro": "Romanian", "hu": "Hungarian", "sv": "Swedish", "da": "Danish", "fi": "Finnish",
    "no": "Norwegian", "ta": "Tamil", "te": "Telugu", "mr": "Marathi", "pa": "Punjabi",
    "tl": "Filipino", "af": "Afrikaans",
}

_ALIASES = {
    "iw": "he", "zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN", "zh-tw": "zh-TW", "zh-hant": "zh-TW",
    "pt-br": "pt", "pt-pt": "pt", "en-us": "en", "en-gb": "en", "nb": "no", "fil": "tl", "jw": "id",
}

# Only where an engine's code differs from ours.
_ENGINE_CODES: dict[str, dict[str, str]] = {
    "google": {"he": "iw", "tl": "tl"},
}


def normalize_language(code: str | None) -> str | None:
    """Canonical code for a user- or detector-supplied one ("EN", "pt-BR", "iw",
    "zh"), or None when we don't support it."""
    if not code:
        return None
    raw = code.strip()
    if raw in LANGUAGES:
        return raw
    low = raw.lower()
    canonical = _ALIASES.get(low, low)
    for known in LANGUAGES:
        if known.lower() == canonical.lower():
            return known
    base = canonical.split("-")[0]
    return base if base in LANGUAGES else None


def engine_code(engine: str, language: str) -> str:
    return _ENGINE_CODES.get(engine, {}).get(language, language)


def base_language(code: str) -> str:
    """"zh-CN" -> "zh", "en" -> "en" — for comparing a detector's answer to a target."""
    return code.split("-")[0].lower()
