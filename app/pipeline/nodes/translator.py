"""
Translate Signals — detects language and translates untranslated Trend rows to English.
Runs before embedding so downstream nodes always see translated_content.

Translation goes through app/translation: one batched, cached call per run
instead of one request per row (the free Google endpoint rate-limits within a
few calls). A row whose translation FAILED keeps translated_content NULL so the
next run retries it. Storing the untranslated text there — what the old
string-only wrapper did on failure — silently marked the row as done, so it was
never retried and got embedded and clustered in the wrong language.
"""
import logging
from app.pipeline.state import PipelineState

logger = logging.getLogger("culturix.pipeline.translator")


def translate_rows(rows, translate_many, detect_language, keep_langs) -> dict:
    """Fill language/translated_content on Trend-like rows in place. Returns counts."""
    counts = {"translated": 0, "kept": 0, "failed": 0, "cached": 0}
    pending = []
    for t in rows:
        text = t.content or t.title or ""
        if not text.strip():
            continue
        t.language = detect_language(text)
        if t.language in keep_langs:
            t.translated_content = text
            counts["kept"] += 1
        else:
            pending.append((t, text))
    if pending:
        results = translate_many([text for _, text in pending], "en")
        for (t, _), result in zip(pending, results):
            if result.ok:
                t.translated_content = result.text
                counts["translated"] += 1
                counts["cached"] += 1 if result.cached else 0
            else:
                counts["failed"] += 1  # left NULL: retried next run
    return counts


def translate_signals(state: PipelineState) -> PipelineState:
    try:
        from app.db import SessionLocal
        from app.models.trend import Trend
        from app.language import KEEP_LANGS, detect_language
        from app.translation import translate_many

        session = SessionLocal()
        try:
            untranslated = (
                session.query(Trend)
                .filter(Trend.translated_content.is_(None))
                .order_by(Trend.id.desc())
                .limit(2000)
                .all()
            )
            counts = translate_rows(untranslated, translate_many, detect_language, KEEP_LANGS)
            session.commit()
            logger.info("Translated rows: %s", counts)
            if counts["failed"]:
                state["errors"] = state.get("errors", []) + [
                    f"translate: {counts['failed']} row(s) left untranslated (translation unavailable), will retry next run"
                ]
        finally:
            session.close()
    except Exception as e:
        logger.error("Translation failed: %s", e)
        state["errors"] = state.get("errors", []) + [f"translate: {e}"]

    return state
