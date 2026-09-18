try:
    from langdetect import detect as _langdetect
    _detection_available = True
except ImportError:
    _detection_available = False

try:
    from deep_translator import GoogleTranslator
    _translation_available = True
except ImportError:
    _translation_available = False

# Languages to keep as-is (no translation needed)
KEEP_LANGS = {"en", "fr", "unknown"}


def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "unknown"
    if not _detection_available:
        return "unknown"
    try:
        return _langdetect(text[:300])
    except Exception:
        return "unknown"


def translate_to_english(text: str) -> str:
    if not _translation_available or not text.strip():
        return text
    try:
        return GoogleTranslator(source="auto", target="en").translate(text)
    except Exception:
        return text


def translate_to_english_if_needed(text: str, source_lang: str) -> str:
    if not text:
        return text
    if source_lang in KEEP_LANGS:
        return text
    return translate_to_english(text)


def translate_text(text: str, target_lang: str = "en") -> str:
    """Translate short UI-facing source text, returning the original on failure."""
    if not text or target_lang not in {"en", "fr", "es"}:
        return text
    if target_lang == "en":
        return translate_to_english(text)
    if not _translation_available:
        return text
    try:
        return GoogleTranslator(source="auto", target=target_lang).translate(text)
    except Exception:
        return text
