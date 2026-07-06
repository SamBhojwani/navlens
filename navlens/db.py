"""Thin Postgres access layer.

Deliberately raw SQL over psycopg2 (no ORM) so the SQL stays visible and defensible.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg2
import psycopg2.extras

from .config import DATABASE_URL


@contextmanager
def get_conn():
    """Yield a connection, committing on success and rolling back on error."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: Sequence[Any] | None = None) -> list[dict]:
    """Run a SELECT and return rows as a list of dicts."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params: Sequence[Any] | None = None) -> None:
    """Run a single write statement."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def insert_batch(sql: str, rows: Iterable[Sequence[Any]], page_size: int = 1000) -> int:
    """Bulk insert using execute_values. `sql` must end with a `VALUES %s` clause.

    Returns the number of rows sent (not the number actually inserted, since
    ON CONFLICT DO NOTHING may skip some).
    """
    rows = list(rows)
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, sql, rows, page_size=page_size)
    return len(rows)


def run_sql_file(path: str | Path) -> None:
    """Execute every statement in a .sql file."""
    sql_text = Path(path).read_text()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
