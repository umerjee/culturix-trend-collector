"""The one place the platform translates text: posts, news headlines, digests,
briefs, and (next) video scripts and narration.

    from app.translation import translate, translate_many

    result = translate("Bonjour", "en")
    result.text, result.ok, result.translated, result.cached

Guarantees:
- **Cached.** Every successful translation is stored (TranslationCache), so a
  repeat is free. Failures are never cached.
- **Honest.** A failure returns the original text with `ok=False` and an error;
  it is never passed off as a translation. Callers that don't care can just use
  `.text`; callers that do (UI badges, narration, anything published) check `.ok`.
- **Cheap.** Text already in the target language, or with nothing translatable
  in it (numbers, URLs, emoji), makes no request. `translate_many` de-duplicates,
  reads the cache in one query, and sends the misses in batches.
- **Safe.** A cache or engine outage degrades to the original text, never an
  exception in a page view.
"""
import hashlib
import logging
import os
import re
from dataclasses import dataclass

from app.translation.engines import EngineError, EngineUnavailable, get_engine
from app.translation.languages import base_language, normalize_language

logger = logging.getLogger("culturix.translation")

# Default order: the free engine first, the LLM only for what it could not do.
ENGINE_CHAIN = ("google", "llm")
# Ceiling on texts sent to the (paid) LLM in one call, so a Google outage during a
# large ingestion run cannot produce an unbounded bill. The rest are reported as
# failed and retried by the next run.
LLM_MAX_TEXTS = int(os.getenv("TRANSLATION_LLM_MAX_TEXTS", "1500"))
# Language detection is unreliable on short strings; only trust it to skip a
# request when there is enough text.
_MIN_CHARS_TO_TRUST_DETECTION = 40


@dataclass
class TranslationResult:
    text: str                 # the translation, or the original when there is nothing to show
    target: str
    ok: bool                  # False only when a translation was needed and failed
    translated: bool          # True when text is a real translation into `target`
    cached: bool = False
    engine: str | None = None
    source: str | None = None
    error: str | None = None


def detect_language(text: str) -> str:
    """Best-effort language code, or "unknown"."""
    if not text or not text.strip():
        return "unknown"
    try:
        from langdetect import detect
        return detect(text[:300])
    except Exception:
        return "unknown"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_translatable_text(text: str) -> bool:
    without_urls = re.sub(r"https?://\S+", " ", text)
    return len(re.sub(r"[\W\d_]+", "", without_urls)) >= 2


def _passthrough(text: str, target: str, source: str | None = None) -> TranslationResult:
    return TranslationResult(text=text, target=target, ok=True, translated=False, source=source)


def _already_in_target(text: str, target: str, source: str) -> bool:
    if source != "auto":
        return base_language(source) == base_language(target)
    if len(text) < _MIN_CHARS_TO_TRUST_DETECTION:
        return False
    detected = detect_language(text)
    return detected != "unknown" and base_language(detected) == base_language(target)


# ── cache ───────────────────────────────────────────────────────────────────

def _cache_get(hashes: list[str], target: str, chain: tuple[str, ...]) -> dict[str, tuple[str, str | None, str]]:
    """{hash: (translated_text, source_lang, engine)} for what is cached under any
    engine in `chain` (earlier engines win); {} on any DB problem."""
    if not hashes:
        return {}
    try:
        from app.db import SessionLocal
        from app.models.translation_cache import TranslationCache
        session = SessionLocal()
        try:
            rows = session.query(TranslationCache).filter(
                TranslationCache.text_hash.in_(hashes), TranslationCache.target_lang == target,
                TranslationCache.engine.in_(chain)).all()
            found: dict[str, tuple[str, str | None, str]] = {}
            for r in sorted(rows, key=lambda r: chain.index(r.engine), reverse=True):  # best engine last -> wins
                found[r.text_hash] = (r.translated_text, r.source_lang, r.engine)
            return found
        finally:
            session.close()
    except Exception:
        logger.warning("Translation cache read failed; translating without it", exc_info=True)
        return {}


def _cache_put(entries: list[tuple[str, str, int]], target: str, engine: str, source: str | None) -> None:
    """entries: (hash, translated_text, source_chars). Best effort."""
    if not entries:
        return
    try:
        from app.db import SessionLocal
        from app.models.translation_cache import TranslationCache
        session = SessionLocal()
        try:
            existing = {h for (h,) in session.query(TranslationCache.text_hash).filter(
                TranslationCache.text_hash.in_([e[0] for e in entries]),
                TranslationCache.target_lang == target, TranslationCache.engine == engine).all()}
            for text_hash, translated, chars in entries:
                if text_hash not in existing:
                    session.add(TranslationCache(text_hash=text_hash, target_lang=target, engine=engine,
                                                 translated_text=translated, source_lang=source, source_chars=chars))
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.warning("Translation cache write failed", exc_info=True)


# ── public API ──────────────────────────────────────────────────────────────

def _chain_for(engine: str | None) -> tuple[str, ...]:
    return ENGINE_CHAIN if engine in (None, "auto") else (engine,)


def translate_many(texts: list[str], target: str, source: str = "auto",
                   engine: str | None = None) -> list[TranslationResult]:
    """Translate several texts into `target`; result i corresponds to texts[i].
    `engine` None/"auto" tries Google then the LLM; "google" or "llm" forces one."""
    canonical = normalize_language(target)
    if canonical is None:
        return [TranslationResult(text=t, target=target, ok=False, translated=False,
                                  error=f"Unsupported language: {target!r}") for t in texts]
    src = "auto" if source == "auto" else (normalize_language(source) or "auto")

    results: list[TranslationResult | None] = [None] * len(texts)
    pending: dict[str, list[int]] = {}   # normalized text -> indices needing it
    for i, text in enumerate(texts):
        if not text or not text.strip() or not _has_translatable_text(text):
            results[i] = _passthrough(text, canonical)
        elif _already_in_target(text, canonical, src):
            results[i] = _passthrough(text, canonical, src if src != "auto" else canonical)
        else:
            pending.setdefault(text.strip(), []).append(i)
    if not pending:
        return results  # type: ignore[return-value]

    unique = list(pending)
    hashes = {t: _hash(t) for t in unique}
    chain = _chain_for(engine)
    cached = _cache_get(list(hashes.values()), canonical, chain)
    misses = []
    for text in unique:
        hit = cached.get(hashes[text])
        if hit:
            for i in pending[text]:
                results[i] = TranslationResult(text=hit[0], target=canonical, ok=True, translated=True,
                                               cached=True, engine=hit[2], source=hit[1])
        else:
            misses.append(text)

    if misses:
        outcome = _translate_misses(misses, hashes, canonical, src, chain)
        for text, result in zip(misses, outcome):
            for i in pending[text]:
                results[i] = result
    return results  # type: ignore[return-value]


def _run_engine(engine_name: str, texts: list[str], hashes: dict[str, str], target: str,
                source: str) -> list[TranslationResult]:
    """One engine over `texts`: a result per text, successes cached, failures flagged."""
    def failed(error: str, subset: list[str] | None = None) -> list[TranslationResult]:
        return [TranslationResult(text=t, target=target, ok=False, translated=False, engine=engine_name,
                                  error=error) for t in (subset if subset is not None else texts)]

    engine = get_engine(engine_name)
    send, over_cap = texts, []
    if engine_name == "llm" and len(texts) > LLM_MAX_TEXTS:
        send, over_cap = texts[:LLM_MAX_TEXTS], texts[LLM_MAX_TEXTS:]
        logger.warning("LLM translation capped at %d of %d texts", LLM_MAX_TEXTS, len(texts))
    try:
        translated = engine.translate_batch(send, target, source)
    except EngineError as exc:
        kind = "unavailable" if isinstance(exc, EngineUnavailable) else "failed"
        logger.warning("Translation (%s) %s for %d text(s) -> %s: %s", engine_name, kind, len(send), target, exc)
        return failed(str(exc)) if not over_cap else failed(str(exc), send) + failed("LLM fallback limit reached", over_cap)
    except Exception as exc:  # an engine bug must not break a page view
        logger.exception("Unexpected translation error (%s)", engine_name)
        return failed(f"{type(exc).__name__}: {exc}"[:200])

    results, to_cache = [], []
    for original, output in zip(send, translated):
        if not output or not output.strip():
            results.append(TranslationResult(text=original, target=target, ok=False, translated=False,
                                             engine=engine_name, error="Empty translation"))
            continue
        results.append(TranslationResult(text=output, target=target, ok=True, translated=True, engine=engine_name,
                                         source=None if source == "auto" else source))
        to_cache.append((hashes[original], output, len(original)))
    _cache_put(to_cache, target, engine_name, None if source == "auto" else source)
    return results + failed("LLM fallback limit reached", over_cap) if over_cap else results


def _translate_misses(misses: list[str], hashes: dict[str, str], target: str, source: str,
                      chain: tuple[str, ...]) -> list[TranslationResult]:
    """Run the engine chain: each engine only sees what the previous ones failed on."""
    final: dict[str, TranslationResult] = {}
    errors: dict[str, list[str]] = {}
    remaining = list(misses)
    for name in chain:
        if not remaining:
            break
        outcome = _run_engine(name, remaining, hashes, target, source)
        still = []
        for text, result in zip(remaining, outcome):
            if result.ok:
                final[text] = result
            else:
                errors.setdefault(text, []).append(f"{name}: {result.error}")
                still.append(text)
        remaining = still
    for text in remaining:
        final[text] = TranslationResult(text=text, target=target, ok=False, translated=False,
                                        engine=chain[-1], error="; ".join(errors.get(text, []))[:300])
    return [final[t] for t in misses]


def translate(text: str, target: str, source: str = "auto", engine: str | None = None) -> TranslationResult:
    return translate_many([text], target, source, engine)[0]
