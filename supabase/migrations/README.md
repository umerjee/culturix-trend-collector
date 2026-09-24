# Scope of this directory

These migrations run against **Supabase's** Postgres — they define the `users`
table mirror, RLS policies, and the `on_auth_user_created` trigger that syncs
Supabase Auth signups. They're pushed automatically via
`.github/workflows/supabase.yml` on any push to `main` that touches this
directory.

**This is not the app's main schema.** Culturix's actual application data
(trends, clusters, personas, content_profiles, generated_content,
generated_media, content_check_log, etc.) lives in a separate **Railway**
Postgres database, and that schema is managed by SQLAlchemy —
`Base.metadata.create_all()` plus a hardcoded list of idempotent
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements in `app/main.py`'s
`lifespan()` function. If you're looking for the current schema of the app's
own tables, read `app/models/*.py` and `app/main.py`'s lifespan block, not
SQL files in this repo — there is no migration-file source of truth for the
Railway database today.

**Before adding a file here, confirm the table already has a `CREATE TABLE`
in this directory.** A 2026-09-24 audit found two migrations
(`region_daily_summaries`, `clusters`) that had been silently blocking every
subsequent Supabase push for two days — `ALTER TABLE`s for Railway-only
tables that were never created here in the first place, so
`supabase db push` failed immediately on the first one and never reached
anything queued behind it. As of that audit, exactly six tables are meant to
exist on Supabase at all: `users`, `subscriptions`, `user_profiles`,
`raw_signals`, `generated_content`, `curated_items` — the first three tied to
the `on_auth_user_created` trigger below, the rest added later for reasons
now lost to time. If your table isn't one of those six, it does not belong
in this directory; add your `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` to
`app/main.py`'s `lifespan()` instead, matching every other Railway-side
column.
