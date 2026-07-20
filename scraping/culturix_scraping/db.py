"""
Async Postgres access for the pipeline, reusing the existing `Trend`
SQLAlchemy model (app/models/trend.py) so this writes into the exact same
`trends` table the rest of Culturix's pipeline (clustering, content
generation) already reads from — whichever spider eventually feeds this
pipeline lands in real data flow, not a disconnected table.

Sharing the declarative model across a sync engine (app/db.py, used by
main.py and the existing collectors) and this async engine is safe: the
model class itself isn't bound to an engine, only Sessions are.

Supabase specifics
-------------------
Supabase's direct connection (port 5432) caps out at a small number of
concurrent Postgres connections — fine for a persistent backend with one
long-lived pool (app/db.py), but a scraping pipeline processing many items
concurrently can exhaust that fast. Point this at Supabase's *transaction
pooler* instead (port 6543; host like aws-0-<region>.pooler.supabase.com;
username suffixed with the project ref) via SUPABASE_POOLER_URL — PgBouncer
fans many short-lived client connections down to a handful of real Postgres
backend connections, which is the actual answer to "high-concurrency writes
without overwhelming Supabase's connection limit." SUPABASE_POOLER_URL is
optional and falls back to DATABASE_URL so this still works unpooled.

PgBouncer's *transaction* pooling mode does not support asyncpg's
server-side prepared statements: a connection handed back to the pool
mid-session can be a *different* physical Postgres backend connection on
the next checkout, so a statement prepared against the old one doesn't
exist on the new one. `statement_cache_size=0` disables asyncpg's
client-side prepared-statement cache to avoid this — skipping it produces
intermittent "prepared statement ... does not exist" errors under real
concurrent load that are hard to reproduce outside a pooled environment.
This is safe to leave on even against a non-pooled Postgres; it only costs
a small amount of per-query overhead.

The SQLAlchemy pool sitting in front of that (pool_size/max_overflow below)
is still worth keeping even though PgBouncer pools underneath it: it's what
lets many concurrent process_item() calls share a bounded number of
persistent logical connections to PgBouncer itself, rather than every item
opening a brand-new one. Keep DB_POOL_SIZE + DB_MAX_OVERFLOW comfortably
under PgBouncer's own max_client_conn, and under Scrapy's CONCURRENT_ITEMS
if you raise that from its default — extra concurrent items just queue for
a pooled connection (bounded by DB_POOL_TIMEOUT_SECONDS) rather than fail.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Explicit, not incidental: app.models.trend below happens to trigger app.db's
# own load_dotenv() as an import side effect, but this module shouldn't rely
# on another module's import order to see DATABASE_URL. Idempotent to call twice.
load_dotenv()

from app.models.trend import Trend  # noqa: E402


def _async_database_url() -> str:
    # Prefer a dedicated pooler URL (Supabase transaction pooler, port 6543)
    # over the direct-connection DATABASE_URL the sync backend uses; falls
    # back to DATABASE_URL so this still works against a plain Postgres
    # instance with no pooler in front of it.
    url = os.getenv("SUPABASE_POOLER_URL") or os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


_engine = create_async_engine(
    _async_database_url(),
    pool_size=_int_env("DB_POOL_SIZE", 20),
    max_overflow=_int_env("DB_MAX_OVERFLOW", 10),
    pool_timeout=_int_env("DB_POOL_TIMEOUT_SECONDS", 30),
    pool_recycle=_int_env("DB_POOL_RECYCLE_SECONDS", 1800),
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0},
)
AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


async def upsert_trend(session: AsyncSession, values: dict[str, Any]) -> None:
    """Insert, or update the mutable engagement fields if (platform, external_id)
    already exists — safe to call repeatedly as the same post's counts grow."""
    stmt = pg_insert(Trend).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Trend.platform, Trend.external_id],
        set_={
            "likes": stmt.excluded.likes,
            "comments": stmt.excluded.comments,
            "shares": stmt.excluded.shares,
            "views": stmt.excluded.views,
            "velocity_score": stmt.excluded.velocity_score,
        },
    )
    await session.execute(stmt)


async def dispose_engine() -> None:
    """Call from the spider's close_spider hook to release pooled connections cleanly."""
    await _engine.dispose()
