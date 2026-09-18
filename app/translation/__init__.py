"""Shared translation for the platform — see service.py for the guarantees."""
from app.translation.languages import LANGUAGES, normalize_language
from app.translation.service import TranslationResult, detect_language, translate, translate_many

__all__ = ["LANGUAGES", "TranslationResult", "detect_language", "normalize_language", "translate", "translate_many"]
