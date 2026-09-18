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

## Known gaps
- Calendar data only covers `calendar_events.TRACKED_REGIONS` (14 countries). Extending holiday sync to more
  countries is cheap (Nager) but changes what `calendar_context` feeds the ideation prompts, so it wasn't done
  silently.
- Mood/sentiment are an LLM judgement, not a measured score; treat as a rough feel.
- Digit check does not catch spelled-out numbers.
