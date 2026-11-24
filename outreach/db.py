"""Database connection helpers (Postgres / Supabase)."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import ROOT


def connect(database_url: str) -> psycopg.Connection:
    if not database_url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    # autocommit: every statement is saved right away; multi-step changes use
    # `with conn.transaction():` so they're saved all-or-nothing.
    # prepare_threshold=None keeps it compatible with Supabase's connection pooler.
    return psycopg.connect(database_url, row_factory=dict_row, prepare_threshold=None,
                           autocommit=True)


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply every SQL file in supabase/migrations (they are written to be re-runnable)."""
    applied = []
    for path in sorted(Path(ROOT / "supabase" / "migrations").glob("*.sql")):
        with conn.transaction():
            conn.execute(path.read_text())
        applied.append(path.name)
    return applied


def get_state(conn, key: str, default=None):
    row = conn.execute("select value from app_state where key = %s", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key: str, value) -> None:
    conn.execute(
        "insert into app_state (key, value) values (%s, %s) "
        "on conflict (key) do update set value = excluded.value",
        (key, Jsonb(value)),
    )
