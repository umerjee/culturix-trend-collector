"""Shared test setup. Registers SQLite-compatible DDL rendering for
Postgres-specific column types (UUID, JSONB) so models that use them (most
of this codebase's models — GeneratedContent, GeneratedMedia, ContentPost,
etc.) can still be exercised against an in-memory SQLite DB in tests,
without changing the production models themselves. Runtime read/write value
handling for these types is dialect-agnostic Python logic already (falls
back to plain json.dumps/loads and str when there's no native driver
support) — only DDL compilation needed a SQLite-specific stand-in."""
import json
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "TEXT"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(element, compiler, **kw):
    return "TEXT"


# ARRAY's DDL now compiles for sqlite (above), but sqlite3's DBAPI still can't
# bind/return a Python list natively the way JSON/JSONB's type objects already
# handle generically — ARRAY has no such fallback, so it needs one here too.
_orig_array_bind_processor = ARRAY.bind_processor
_orig_array_result_processor = ARRAY.result_processor


def _array_bind_processor_with_sqlite_fallback(self, dialect):
    if dialect.name == "sqlite":
        return lambda value: json.dumps(value) if value is not None else None
    return _orig_array_bind_processor(self, dialect)


def _array_result_processor_with_sqlite_fallback(self, dialect, coltype):
    if dialect.name == "sqlite":
        return lambda value: json.loads(value) if value is not None else None
    return _orig_array_result_processor(self, dialect, coltype)


ARRAY.bind_processor = _array_bind_processor_with_sqlite_fallback
ARRAY.result_processor = _array_result_processor_with_sqlite_fallback
