# Daily country brief

A 2-3 sentence brief per country per day on the World region page: calendar + what people engaged with,
compared with live news and the country's own recent history. Code: `app/services/region_daily_summary.py`,
model `RegionDailySummary`, public read endpoint `GET /world/regions/{code}/summary`, UI
`culturix-web/src/components/world/DailyBrief.tsx` (rendered inside `TimeCursor`, follows the slider).

## How it runs
- The scheduler (`run_region_summaries`, 08:15 and 20:15 UTC, after the 07:00/19:00 collections) generates
  today's brief for every eligible region and caches it. **A page view never triggers generation** (public
  endpoint, so that would be an LLM-cost hole).
- Backfill history / run by hand: `python scripts/generate_region_summaries.py --days 14` (oldest day first,
  so each day's stored mood becomes history for the next). `--dry-run` shows inputs, `--no-llm` is free.

## Rules (each from something measured, not assumed)
- **Real inputs only.** Any number in the output that isn't in the inputs invalidates it -> deterministic
  template built from real titles. The prompt forbids inventing events, causes, names or numbers.
- **Clean before summarizing.** Top-liked TikTok titles are mostly `[Audio: original sound ...]`, hashtag walls
  and spam, so `clean_title` drops those and `pick_topics` samples <=3 per platform round-robin. This is both
  the quality fix and the token saving.
- **Thin data says nothing.** Of ~76 regions the API lists, only ~13 have real daily volume and ~22 have 50+
  rows; the rest have 1-3 stray rows. A region needs `MIN_SIGNALS` rows AND `MIN_CLEAN_TOPICS` usable titles,
  else a calendar-only line (if an event exists) or no brief.
- **"Versus usual" needs history.** The 7-day baseline (volume, average likes, new themes) is only used with
  `MIN_BASELINE_DAYS` prior days; otherwise the prompt says so and forbids a comparison.
- **News = Google News RSS, that country's own edition** (`app/collectors/news.py`). Asking for an English
  edition of a country without one silently returns the US edition (Egypt returned the same BBC story as the
  US), so only countries with a genuine edition get one; the rest get no news, never someone else's. News is a
  live lookup, so it is only fetched for today; backfilled days have none. Raw headlines are stored for audit
  and never exposed by the API.
- **GDELT was tried and rejected**: its tone-timeline API answered HTTP 429 to every request, even after a
  long pause. Historic sentiment is therefore our own: mood/sentiment stored per day, plus the baseline above.
- **Cache skip.** `inputs_hash` (includes `PROMPT_VERSION`) means unchanged inputs skip the LLM entirely.
  **Bump `PROMPT_VERSION` whenever `build_prompt` changes**, or cached rows keep the old wording.
- Calendar rows sourced `llm_generated` (sports/music) are passed as "unverified expectation".

## Audience archetypes (`top_persona_matches`, 2026-09-22)
A region's brief also carries `audience_matches`: up to `MAX_PERSONA_MATCHES` real, already-generated Persona
rows (`app/models/persona.py` — this platform's own cross-trend clustering, run once across the whole corpus,
never a real individual and never region-specific by construction) whose stated interests best match what's
trending here today. This is the actual differentiator over a raw trend feed: not just what's trending, but
who an audience for it is, in terms already proven to work for content matching elsewhere in this product
(`culturetoon_trend_relevance.py`'s identical Voyage.ai cosine-similarity mechanism, reused not duplicated
for the math, `_cosine_similarity` kept local per this module's existing no-cross-coupling convention).

**Deterministic, not LLM-written**: the model never sees or writes a persona name — `top_persona_matches` is a
plain DB query + cosine ranking, called from `gather_inputs` and stored on `RegionDailySummary.audience_matches`
independent of whether the summary text itself came from the LLM, the template, or the calendar-only path (it
still gets computed whenever there's `enough` topic/theme data). One new Voyage embedding call per region per
day (the query text); the 465/764 Personas that already have a cached `relevance_embedding` cost nothing.

`PERSONA_MATCH_MIN_SCORE = 0.20` is measured, not guessed — see the constant's own comment. An untested first
guess of 0.35 silently excluded "Marvel Stan" (0.276) from a Marvel-trailer query and "Die-Hard Sports Fan"
(0.314) from a football story; real matches in this corpus cluster at 0.15-0.43 while unrelated personas sit
at ~0.05-0.09. Re-verify with a live query (see this doc's own scratch pattern: embed a few on-the-nose
queries and print the sorted scores) before changing this number again.

## Known gaps
- Calendar data only covers `calendar_events.TRACKED_REGIONS` (14 countries). Extending holiday sync to more
  countries is cheap (Nager) but changes what `calendar_context` feeds the ideation prompts, so it wasn't done
  silently.
- Mood/sentiment are an LLM judgement, not a measured score; treat as a rough feel.
- Digit check does not catch spelled-out numbers.
- The news-contrast sentence sometimes lands as a "While X..." fragment rather than a full second sentence
  despite an explicit prompt instruction against it (tried 2026-09-22, model didn't reliably follow it) —
  cosmetic, not a validation failure; worth another prompt pass if it keeps showing up.
