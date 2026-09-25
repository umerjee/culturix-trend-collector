import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

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

# 6. Dependency for FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
