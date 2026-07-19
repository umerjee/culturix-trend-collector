"""
Translate Signals — detects language and translates untranslated Trend rows to English.
Runs before embedding so downstream nodes always see translated_content.
"""
import logging
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.translator")


def translate_signals(state: PipelineState) -> PipelineState:
    try:
        from app.db import SessionLocal
        from app.models.trend import Trend
        from app.language import detect_language, translate_to_english_if_needed

        session = SessionLocal()
        try:
            untranslated = (
                session.query(Trend)
                .filter(Trend.translated_content.is_(None))
                .order_by(Trend.id.desc())
                .limit(2000)
                .all()
            )
            for t in untranslated:
                text = t.content or t.title or ""
                if not text.strip():
                    continue
                t.language = detect_language(text)
                t.translated_content = translate_to_english_if_needed(text, t.language)
            session.commit()
            logger.info("Translated %d rows", len(untranslated))
        finally:
            session.close()
    except Exception as e:
        logger.error("Translation failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"translate: {e}"]

    return state
