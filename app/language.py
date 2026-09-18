"""Compatibility wrappers over app/translation, kept so the collectors, the
ingestion pipeline and the World router (about 20 call sites) don't change.
New code should import from app.translation directly: it returns a result that
says whether the translation actually happened, which these string-only
wrappers cannot.

On failure these return the original text (the old behaviour) — the failure is
logged and never cached, but the caller cannot see it. Use app.translation for
anything that gets published.
"""
from app.translation import translate
from app.translation.service import detect_language as _detect_language

# Languages the ingestion pipeline keeps as-is (no translation to English).
KEEP_LANGS = {"en", "fr", "unknown"}


def detect_language(text: str) -> str:
    return _detect_language(text)


def translate_to_english(text: str) -> str:
    if not text or not text.strip():
        return text
    return translate(text, "en").text


def translate_to_english_if_needed(text: str, source_lang: str) -> str:
    if not text:
        return text
    if source_lang in KEEP_LANGS:
        return text
    return translate_to_english(text)


def translate_text(text: str, target_lang: str = "en") -> str:
    """Translate short UI-facing text into any supported language; the original on failure."""
    if not text:
        return text
    return translate(text, target_lang).text
