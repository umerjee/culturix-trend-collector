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
