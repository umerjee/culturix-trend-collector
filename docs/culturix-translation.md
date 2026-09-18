# Translation module

One place the platform translates text: `app/translation/`. Posts, news, digests and briefs use it now; video
scripts and narration are the next callers. `app/language.py` is a thin compatibility layer over it so the ~20
existing call sites (collectors, ingestion, World router) didn't have to change.

```python
from app.translation import translate, translate_many
r = translate("Bonjour", "en")      # r.text, r.ok, r.translated, r.cached, r.error
rs = translate_many(texts, "de")    # batched + de-duplicated + cached, order preserved
```

## Guarantees
- **Cached** (`translation_cache`, keyed by SHA-256 of the text + target + engine; the source text is not stored).
  Failures are never cached.
- **Honest.** A failure returns the original text with `ok=False` and an `error`. Anything that gets *published*
  must check `.ok`. The string-only wrappers in `app/language.py` still return the original on failure (their old
  contract) and cannot report it — use `app.translation` for new code.
- **Cheap.** No request for empty text, numbers/URLs/emoji, or text already in the target language (detection is
  only trusted on 40+ characters). Misses go out several per request.
- **Safe.** A cache or engine outage degrades to the original text; it never raises into a page view.
- **Languages:** the registry in `languages.py` (~40, one line each to add). Codes are normalized (`pt-BR`->`pt`,
  `zh`->`zh-CN`, `iw`->`he`).

## Google only, and why it needed care (all measured)
- The free endpoint (deep_translator 1.9.1) **rate-limits within a handful of calls**: one failure, then "too many
  requests" on every call after it. It was already limited on this dev machine before any test ran. So
  `GoogleEngine` has: a global throttle (0.35s gap), several texts per request joined by newlines and **verified
  by line count** (falls back to one-per-text if Google merges lines), backoff, and a **circuit breaker** (3
  rate-limit failures -> refuse calls for 90s, so pages fail fast instead of hanging).
- **Hebrew must be sent as `iw`** (`he` is rejected). Per-engine code mapping lives in `languages.py`.
- Requests over 5000 chars are rejected; long text is split on line boundaries (`MAX_REQUEST_CHARS` 4500).
- Live status when this was written: Google was throttling the dev machine, so the module was verified live only
  for its failure behaviour (fast, flagged, nothing cached); success paths are unit-tested with a fake engine.

## A bug this fixed
The ingestion node stored whatever the wrapper returned in `trends.translated_content`. On failure that was the
**untranslated text**, which marked the row done (never retried) and let it be embedded and clustered in the
wrong language. `translate_rows` (used by the pipeline node and `/process/translations`) now leaves a failed row
NULL so the next run retries it, and reports the count in the pipeline errors. It also sends one batched call per
run instead of one request per row.

## Next
- **Video narration:** LTX-2.5 generates the audio from the script text, so "translated narration" means writing
  or translating the *script* per language and then rendering — not translating audio afterwards. Narration
  should check `.ok` and refuse to render on a failed translation.
- **LLM engine** (Qwen/Claude) behind the same `TranslationEngine` interface, routed by content type (narration
  and news benefit; bulk posts don't). Also the fallback if the free Google endpoint stays unreliable in
  production. Register it in `engines.get_engine` and pass `engine=` — no caller changes.
