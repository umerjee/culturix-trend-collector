import os
import time
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

logger = logging.getLogger("culturix.db")

# 1. Load environment variables
load_dotenv()

# 2. Read DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL")

# A bare "postgresql://" (no explicit "+driver") leaves SQLAlchemy to pick a postgres DBAPI
# on its own — confirmed live in CI (2026-09-25): a fresh `pip install` with SQLAlchemy left
# unpinned in requirements.txt resolved to the psycopg (v3) dialect instead of psycopg2, and
# only psycopg2-binary is an actual dependency here, so every test module importing this file
# failed with "No module named 'psycopg'" — 41 collection errors, all from this one line.
# Both this app's real Railway DATABASE_URL and the CI/dev placeholder use the bare scheme,
# so production was equally exposed to the same break on its next fresh dependency install,
# not just CI. Forcing the driver explicitly makes the choice deterministic regardless of
# which SQLAlchemy version ends up installed, rather than depending on its internal
# preference/fallback order.
def _force_psycopg2_driver(url: str | None) -> str | None:
    if url and url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = _force_psycopg2_driver(DATABASE_URL)

# 3. Create engine
# pool_pre_ping: confirmed live 2026-08-20 — a long-running background task
# (LoRA training, which holds one session open across several minutes of
# SSH-driven pod work with no DB activity in between) hit
# psycopg2.OperationalError: server closed the connection unexpectedly when
# it finally tried to commit, because the pooled connection had gone stale
# in the meantime (Supabase's connection pooler drops idle connections).
# pool_pre_ping makes SQLAlchemy test a pooled connection before handing it
# out, transparently reconnecting if it's gone stale, instead of surfacing
# the DB error as if it were the actual failure being reported.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# 4. Create Base class for models
Base = declarative_base()

# 5. Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_COMMIT_RETRY_ATTEMPTS = 6
_COMMIT_RETRY_BACKOFF_SECONDS = 15


def resilient_commit(session, mutate) -> None:
    """Commit with retry for the specific failure pool_pre_ping above does NOT cover: a session
    held open across a long external call (an LLM generation chain, a GPU render, an SSH-driven
    training job) with no DB traffic in between. pool_pre_ping only re-validates a connection at
    CHECKOUT time; one that goes stale while actively held and never returned to the pool isn't
    caught until the next query on it fails outright. Confirmed live as the same root cause four
    separate times now: LoRA training (2026-08-20, prompted pool_pre_ping's addition above, which
    only partially covers this), the self-hosted render pipeline (2026-08-26, twice, which is
    where this function originated as a local helper before being promoted here), and the World
    regeneration campaign (2026-09-29/30) -- world_production.py's generate_world_draft and
    improve_world_draft held a session across multi-minute script-generation and thumbnail calls
    with a bare db.commit() at the end and no retry, losing real work to "server closed the
    connection unexpectedly" / "SSL connection has been closed unexpectedly" every time it hit.

    Takes `mutate` (a callback that re-applies the intended field assignments) rather than just
    retrying a bare commit() -- session.rollback() expires every object in the session by
    default, so a naive "rollback, then commit() again" retry silently commits *nothing*, since
    the in-memory attribute changes set before the first failed commit are gone the moment
    rollback() runs. Re-running `mutate` each attempt (idempotent field assignments only -- never
    call an external API again inside it, just reassign already-computed values) is what actually
    makes the retry do something."""
    last_exc = None
    for attempt in range(_COMMIT_RETRY_ATTEMPTS):
        try:
            mutate()
            session.commit()
            return
        except Exception as exc:
            last_exc = exc
            session.rollback()
            logger.warning("resilient_commit attempt %d/%d failed: %s", attempt + 1, _COMMIT_RETRY_ATTEMPTS, exc)
            if attempt < _COMMIT_RETRY_ATTEMPTS - 1:
                time.sleep(_COMMIT_RETRY_BACKOFF_SECONDS)
    raise last_exc

# 6. Dependency for FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
