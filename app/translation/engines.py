"""Translation engines. Only Google (the free public endpoint, through
deep_translator) is wired for now; the interface is small so an LLM engine
(better on tone, idiom and narration) can be added and routed to later without
touching any caller.

Google's free endpoint is fragile, and this was measured, not assumed: a single
failed call was followed by "too many requests" on every call after it. So the
engine itself carries the protections a caller can't:
- a global throttle (calls are serialised with a minimum gap),
- several short texts per request (joined by newlines, verified by line count),
- backoff on rate limiting,
- a circuit breaker: after repeated rate-limit failures it refuses calls for a
  cooldown instead of hanging every page that asks for a translation.
"""
import logging
import threading
import time
from typing import Protocol

from app.translation.languages import engine_code

logger = logging.getLogger("culturix.translation.engines")

MAX_REQUEST_CHARS = 4500   # Google's public endpoint rejects >5000 chars per request
MAX_BATCH_ITEMS = 40


class EngineError(Exception):
    """A failed translation request."""


class EngineUnavailable(EngineError):
    """The engine is rate-limited or its circuit breaker is open."""


class TranslationEngine(Protocol):
    name: str

    def translate_batch(self, texts: list[str], target: str, source: str = "auto") -> list[str]:
        """Translate each text; result i is the translation of texts[i]. Raises EngineError."""


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "too many requests" in text or "429" in text or "rate" in text and "limit" in text


class GoogleEngine:
    name = "google"

    MIN_GAP_SECONDS = 0.35
    BACKOFF_SECONDS = (2.0, 5.0)
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_SECONDS = 90.0

    def __init__(self):
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._consecutive_rate_limits = 0
        self._open_until = 0.0

    # -- low level ----------------------------------------------------------
    def _client(self, target: str, source: str):
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source=engine_code(self.name, source) if source != "auto" else "auto",
                                target=engine_code(self.name, target))

    def _call(self, text: str, target: str, source: str) -> str:
        """One throttled request, with backoff and breaker accounting."""
        for attempt in range(len(self.BACKOFF_SECONDS) + 1):
            with self._lock:
                now = time.monotonic()
                if now < self._open_until:
                    raise EngineUnavailable("Google translation is cooling down after rate limiting")
                wait = self._last_call + self.MIN_GAP_SECONDS - now
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.monotonic()
                try:
                    result = self._client(target, source).translate(text)
                except Exception as exc:
                    if _is_rate_limit(exc):
                        self._consecutive_rate_limits += 1
                        if self._consecutive_rate_limits >= self.BREAKER_THRESHOLD:
                            self._open_until = time.monotonic() + self.BREAKER_COOLDOWN_SECONDS
                            self._consecutive_rate_limits = 0
                            raise EngineUnavailable("Google translation rate-limited; pausing") from exc
                        error: Exception = exc
                    else:
                        raise EngineError(str(exc)[:200]) from exc
                else:
                    self._consecutive_rate_limits = 0
                    return result if isinstance(result, str) else str(result or "")
            # rate limited: back off outside the lock so other threads aren't blocked on our sleep
            if attempt < len(self.BACKOFF_SECONDS):
                time.sleep(self.BACKOFF_SECONDS[attempt])
        raise EngineUnavailable("Google translation rate-limited") from error

    # -- public -------------------------------------------------------------
    def translate_batch(self, texts: list[str], target: str, source: str = "auto") -> list[str]:
        results: list[str] = [""] * len(texts)
        for indices in self._group(texts):
            group = [texts[i] for i in indices]
            translated = self._translate_group(group, target, source)
            for i, text in zip(indices, translated):
                results[i] = text
        return results

    @staticmethod
    def _group(texts: list[str]) -> list[list[int]]:
        """Indices grouped so each group fits one request."""
        groups, current, size = [], [], 0
        for i, text in enumerate(texts):
            cost = len(text) + 1
            if current and (size + cost > MAX_REQUEST_CHARS or len(current) >= MAX_BATCH_ITEMS):
                groups.append(current)
                current, size = [], 0
            current.append(i)
            size += cost
        if current:
            groups.append(current)
        return groups

    def _translate_group(self, group: list[str], target: str, source: str) -> list[str]:
        if len(group) == 1:
            return [self._translate_long(group[0], target, source)]
        # Newlines survive translation, so one request can carry several short
        # texts. Verified by line count: if Google merged or split lines, fall
        # back to one request per text rather than misalign translations.
        clean = [" ".join(t.split()) or "." for t in group]
        joined = self._call("\n".join(clean), target, source)
        lines = joined.split("\n")
        if len(lines) == len(group):
            return [line.strip() for line in lines]
        logger.info("Batch translation returned %d lines for %d texts; translating individually", len(lines), len(group))
        return [self._translate_long(t, target, source) for t in group]

    def _translate_long(self, text: str, target: str, source: str) -> str:
        """One text, split on sentence/line boundaries if over the request limit."""
        if len(text) <= MAX_REQUEST_CHARS:
            return self._call(text, target, source)
        parts, current = [], ""
        for piece in text.replace("\r", "").split("\n"):
            while len(piece) > MAX_REQUEST_CHARS:  # a single huge line: hard split
                if current:
                    parts.append(current)
                    current = ""
                parts.append(piece[:MAX_REQUEST_CHARS])
                piece = piece[MAX_REQUEST_CHARS:]
            if current and len(current) + len(piece) + 1 > MAX_REQUEST_CHARS:
                parts.append(current)
                current = piece
            else:
                current = f"{current}\n{piece}" if current else piece
        if current:
            parts.append(current)
        return "\n".join(self._call(part, target, source) for part in parts)


_ENGINES: dict[str, TranslationEngine] = {}


def get_engine(name: str = "google") -> TranslationEngine:
    """Engine by name; one shared instance each so throttle and breaker state is global."""
    if name not in _ENGINES:
        if name != "google":
            raise ValueError(f"Unknown translation engine: {name!r}")
        _ENGINES[name] = GoogleEngine()
    return _ENGINES[name]
