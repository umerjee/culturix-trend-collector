"""One-off diagnostic: which tables are actually consuming space in the
Railway-hosted Postgres DB. Not part of the app — run by hand:
    python scripts/check_db_size.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 10})

with engine.connect() as conn:
    total = conn.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar()
    print(f"Total DB size: {total}\n")

    rows = conn.execute(text("""
        SELECT
            relname AS table_name,
            pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
            pg_size_pretty(pg_relation_size(relid)) AS table_size,
            pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) AS index_size,
            (SELECT reltuples::bigint FROM pg_class WHERE oid = relid) AS approx_row_count
        FROM pg_catalog.pg_statio_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 25
    """)).fetchall()

    print(f"{'table':30} {'total':>10} {'table':>10} {'indexes':>10} {'~rows':>12}")
    for r in rows:
        print(f"{r.table_name:30} {r.total_size:>10} {r.table_size:>10} {r.index_size:>10} {r.approx_row_count:>12}")

    print("\nOldest/newest rows in likely-unbounded tables:")
    for table, ts_col in [
        ("raw_signals", "created_at"),
        ("trends", "collected_at"),
        ("generated_content", "generated_at"),
        ("content_post_snapshots", "captured_at"),
    ]:
        try:
            row = conn.execute(text(
                f"SELECT COUNT(*), MIN({ts_col}), MAX({ts_col}) FROM {table}"
            )).fetchone()
            print(f"  {table:25} count={row[0]:<10} oldest={row[1]} newest={row[2]}")
        except Exception as e:
            print(f"  {table:25} skipped ({e})")
