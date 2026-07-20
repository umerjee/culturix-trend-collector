# culturix_scraping — trend velocity pipeline

A standalone Scrapy `ItemPipeline` (dedup → velocity scoring → Postgres
upsert → high-velocity hook) for whatever spider eventually feeds it. It is
**not** a spider, and deliberately doesn't include one — see "Scope" below.

## Scope

This package processes items; it does not collect them. There is no spider,
proxy rotation, or fingerprint/header-spoofing middleware here, and none will
be added to this package — building infrastructure to evade a platform's bot
detection isn't something this covers. Point a compliant spider (an official
API client, e.g. TikTok's Research API, or a licensed data provider) at
`TrendVelocityPipeline`, and it handles everything from there.

## What it does

1. **Dedup** (`dedup.py`) — in-memory by default; set `REDIS_URL` for
   cross-run/cross-worker dedup via Redis SETs with a 7-day TTL.
2. **Velocity scoring** (`velocity.py`) — `like_count / (hours_since_posted + 1)`.
3. **Storage** (`db.py`) — async upsert into the *same* `trends` table the
   main Culturix backend (`app/`) already reads from for clustering and
   content generation, keyed on `(platform, external_id)`. Uses a bounded
   SQLAlchemy async connection pool over asyncpg, and is built to sit behind
   Supabase's transaction pooler (PgBouncer, port 6543) rather than the
   direct connection — see "Supabase connection pooling" below.
4. **Event hook** (`hooks.py`) — when a score crosses `VELOCITY_THRESHOLD`,
   POSTs a payload to `CONTENT_ENGINE_WEBHOOK_URL` if set, otherwise logs it.

## Setup

```bash
pip install -r scraping/requirements.txt
```

This package imports `app.models.trend.Trend` from the main backend to share
its schema, so run it with the repo root on `PYTHONPATH` (e.g. from the repo
root: `PYTHONPATH=. scrapy crawl <your_spider>`) and the same `DATABASE_URL`
the backend uses.

**One-time schema setup** — `app/main.py`'s `lifespan()` already adds the
`trends.velocity_score` column and the `(platform, external_id)` unique index
`ON CONFLICT` needs; either start the backend once against the same
`DATABASE_URL`, or run `python -m app.init_db` from the repo root.

Env vars:

| Var | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Same Postgres the main backend uses (`postgresql://…`; the driver is swapped to `asyncpg` internally). Used as a fallback if `SUPABASE_POOLER_URL` isn't set. |
| `SUPABASE_POOLER_URL` | recommended | Supabase's transaction pooler connection string (port 6543) — see below. Takes priority over `DATABASE_URL` when set. |
| `REDIS_URL` | no | Cross-run dedup; falls back to in-memory if unset or unreachable |
| `CONTENT_ENGINE_WEBHOOK_URL` | no | Where high-velocity items get POSTed; falls back to a log line if unset |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | no | Bounded async pool size (default 20 / 10 = 30 max concurrent connections) |
| `DB_POOL_TIMEOUT_SECONDS` / `DB_POOL_RECYCLE_SECONDS` | no | How long a checkout waits before erroring (default 30s) / how often idle connections are recycled (default 1800s) |

Copy the relevant settings from `culturix_scraping/settings_example.py`
(reactor, pipeline registration, threshold) into your Scrapy project's real
`settings.py` once a spider exists.

### Supabase connection pooling

Supabase's **direct connection** (port 5432) allows only a small number of
concurrent Postgres connections — fine for the main backend's one long-lived
pool (`app/db.py`), but a spider writing at real concurrency can exhaust it
fast, including starving the main backend of connections. Use the
**transaction pooler** instead:

1. In the Supabase dashboard: Project Settings → Database → Connection
   pooling → copy the "Transaction" mode connection string (port `6543`,
   host like `aws-0-<region>.pooler.supabase.com`, username suffixed with
   your project ref).
2. Set it as `SUPABASE_POOLER_URL`.

`db.py` already sets `statement_cache_size=0`, which is **required** for
correctness under PgBouncer transaction mode — without it you'll see
intermittent `prepared statement "..." does not exist` errors under load,
because a pooled connection handed back mid-session can be a different
physical Postgres backend connection than the one a statement was prepared
against. This is safe to leave on even without a pooler; the cost is a small
amount of per-query overhead, not a correctness risk.

Keep `DB_POOL_SIZE + DB_MAX_OVERFLOW` comfortably under the pooler's own
`max_client_conn`, and under Scrapy's `CONCURRENT_ITEMS` if you raise it from
its default — extra concurrent items simply queue for a pooled connection
(bounded by `DB_POOL_TIMEOUT_SECONDS`) rather than fail outright.

## Data sources

### Apify (recommended today — `collectors/trend_apify_ingestor.py`)

Same `apify-client` pattern already used in `app/collectors/xiaohongshu.py`
and `app/collectors/twitter_apify.py`. Two ways to get a dataset — there's no
spider or `scrapy crawl` involved either way, just a standalone async script:

```bash
# Cheapest: read an already-finished dataset, no new run triggered
APIFY_API_TOKEN=... APIFY_DATASET_ID=... \
  PYTHONPATH=<repo-root> python -m culturix_scraping.collectors.trend_apify_ingestor

# Recurring/scheduled use: trigger a fresh run each time (a dataset is a
# static snapshot, so re-reading the same APIFY_DATASET_ID on a schedule
# would just re-ingest identical data forever)
APIFY_API_TOKEN=... APIFY_ACTOR_ID=apidojo/tweet-scraper APIFY_SEARCH_TERMS="ai,startups" \
  PYTHONPATH=<repo-root> python -m culturix_scraping.collectors.trend_apify_ingestor
```

| Var | Required | Purpose |
|---|---|---|
| `APIFY_API_TOKEN` | yes | Your Apify API token |
| `APIFY_DATASET_ID` | one of this or the two below | The dataset to read (from an actor run triggered elsewhere) |
| `APIFY_ACTOR_ID` + `APIFY_SEARCH_TERMS` | — | Trigger a fresh actor run instead; `APIFY_DATASET_ID` wins if both are set |
| `APIFY_MAX_ITEMS` | no | Cap per triggered run (default `60`) — only relevant with `APIFY_ACTOR_ID` |
| `APIFY_PLATFORM` | no | Forces `platform` for every row; otherwise inferred from an item field or a `tiktok.com`/`instagram.com`/`twitter.com`/`x.com` URL host, and rows that can't be identified either way are skipped and counted, not guessed at |

It's actor-agnostic within reason — `map_apify_item()` (in that file) checks
a handful of common field-name variants (`playCount`/`viewCount`,
`diggCount`/`likeCount`, `createTimeISO`/`takenAtTimestamp`, etc.) used across
popular TikTok/Instagram actors on Apify's store. If your actor's output uses
different field names, extend the key lists there rather than writing a new
mapper from scratch.

### ScrapeCreators (in parallel, evaluating — `collectors/trend_scrapecreators_ingestor.py`)

Direct async HTTP calls via `httpx` (no actor-run/dataset lifecycle like
Apify) to ScrapeCreators' hashtag-search endpoints, authenticated with a
single `x-api-key` header. Same downstream pipeline as the Apify ingestor —
only the fetch-and-map layer differs.

```bash
SCRAPE_CREATORS_API_KEY=... SCRAPE_CREATORS_SEARCH_TERMS="ai,startups" \
  PYTHONPATH=<repo-root> python -m culturix_scraping.collectors.trend_scrapecreators_ingestor
```

| Var | Required | Purpose |
|---|---|---|
| `SCRAPE_CREATORS_API_KEY` | yes | Your ScrapeCreators API key |
| `SCRAPE_CREATORS_SEARCH_TERMS` | yes | Comma-separated hashtags/keywords to search |
| `SCRAPE_CREATORS_PLATFORM` | no | `tiktok` (default), `instagram`, or `threads` |
| `SCRAPE_CREATORS_MAX_PAGES` | no | Pages to paginate per search term (default `1` — each page is 1 API credit) |

Field names are grounded against ScrapeCreators' published docs, not
guessed — but the Apify integration needed a live-data fix for exactly this
reason (an actor's real output didn't match its docs), so treat this the
same way: run it once against a real key before trusting it, especially
Instagram. Specifically unconfirmed: TikTok's and Threads' responses wrap
items in known keys (`aweme_list`, `posts` respectively, both confirmed
against docs). Instagram's wrapper key isn't shown in the docs this was
built against, so `_extract_items()` tries several common candidates
(`data`/`posts`/`items`/`results`) and logs a warning listing the actual
top-level keys if none match — check that log line first if Instagram comes
back with 0 items.

Known per-platform schema quirks (all handled in the mapper, worth knowing
if debugging a 0-mapped run):
- **TikTok**: engagement stats **nested** under `statistics.*`
  (`statistics.digg_count`, not `diggCount`); `create_time` is Unix epoch
  seconds; search param is `hashtag`.
- **Instagram**: flat fields; `taken_at` is an ISO 8601 **string**; **no
  share_count field at all** (always 0, not a bug); search param is
  `hashtag`.
- **Threads**: search param is `query` (a keyword search, not hashtag);
  `taken_at` is the *same field name* as Instagram's but a Unix epoch
  **integer** here, not a string; text is nested at `caption.text`;
  reply/repost counts nested under `text_post_app_info.*`; no view_count
  field. Docs claim a 10-result cap per query — a live test run returned 19,
  so that limit either doesn't hold anymore or was never accurate; the code
  doesn't assume any particular count.

**Live-tested** (2026-07-20): all three platforms mapped 100% of returned
items with zero errors on the first real run — TikTok 20/20, Instagram 9/9,
Threads 19/19.

### Anything else

A spider just needs to yield dicts (or `items.TrendItem`) shaped like:

```python
yield {
    "video_id": "7123456789",
    "platform": "tiktok",
    "description": "...",
    "view_count": 120_000,
    "like_count": 8_400,
    "share_count": 310,
    "comment_count": 96,
    "created_at": "2026-01-01T12:00:00Z",  # or epoch seconds, or a datetime
}
```

`TrendVelocityPipeline.process_item` validates it via `TrendRecord.from_item`,
drops malformed/duplicate items with `DropItem`, and returns the item with
`velocity_score` attached.

## Scheduling (`run_scheduled_ingest.py`)

Both ingestors above are manual-trigger scripts by default. `run_scheduled_ingest.py`
runs either or both on a recurring cron schedule — but as its **own process**,
not inside the main backend. See the module docstring for the full reasoning;
short version: wiring this into `app/scheduler.py` (the main backend's
in-process APScheduler) would mean bundling `scraping/`'s dependencies into
the deployed backend, which was kept separate on purpose.

```bash
cd scraping
SCHEDULE_APIFY=true APIFY_API_TOKEN=... APIFY_ACTOR_ID=apidojo/tweet-scraper APIFY_SEARCH_TERMS="ai,startups" \
SCHEDULE_SCRAPECREATORS=true SCRAPE_CREATORS_API_KEY=... SCRAPE_CREATORS_SEARCH_TERMS="ai,startups" \
  python run_scheduled_ingest.py
```

Each ingestor is independently opt-in (`SCHEDULE_APIFY=true` / `SCHEDULE_SCRAPECREATORS=true`);
run one, both, or write your own script importing `register_jobs()` if you
want different scheduling logic. Default cadence is every 6 hours
(`APIFY_CRON_HOUR` / `SCRAPE_CREATORS_CRON_HOUR`, APScheduler cron syntax).
Note the Apify ingestor needs `APIFY_ACTOR_ID` + `APIFY_SEARCH_TERMS` (not
`APIFY_DATASET_ID`) to mean anything on a recurring schedule — a dataset is a
static snapshot of one past run, so re-reading the same ID forever is a
no-op after the first run.

This has **not** been run continuously / left on for an extended period —
only validated that job registration and each ingestor individually work.
Watch API credit consumption closely the first few cycles before trusting it
unattended.

## Tests

```bash
cd scraping
pip install -r requirements.txt
pytest tests/
```

Needs both the repo root and `scraping/` on `PYTHONPATH` (the ingestor imports
`app.models.trend`, and tests import `culturix_scraping`) — from the repo
root:

```bash
PYTHONPATH=.:scraping pytest scraping/tests/
```

`test_velocity.py` has no extra dependencies beyond pytest. The rest need
`scrapy` installed (all import `culturix_scraping.pipelines`, which imports
`scrapy`). Not wired into the main repo's `pytest.ini`/CI since this package
isn't part of the deployed backend yet. All 67 tests pass as of this writing.
