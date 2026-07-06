"""Test fixtures. DB tests run against a dedicated `navlens_test` database so they
never touch real data. Requires the Docker Postgres (docker compose up -d) to be running.
"""
import os
from pathlib import Path

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parent.parent
_BASE = os.environ.get("TEST_PG_BASE", "postgresql://navlens:navlens@localhost:5433")

# Point every navlens module at the test database *before* importing them.
os.environ["DATABASE_URL"] = f"{_BASE}/navlens_test"


def _ensure_test_db() -> None:
    conn = psycopg2.connect(f"{_BASE}/navlens")
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE DATABASE navlens_test")
    except psycopg2.errors.DuplicateDatabase:
        pass
    finally:
        conn.close()


_ensure_test_db()

from navlens import analytics, db  # noqa: E402  (import after env + db creation)
from navlens.ingest import NavRecord  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the schema and views once for the test session."""
    db.run_sql_file(ROOT / "sql" / "01_schema.sql")
    db.run_sql_file(ROOT / "sql" / "02_views.sql")
    yield


@pytest.fixture
def clean_db():
    """Empty all tables before a test that needs a known starting state."""
    db.execute("TRUNCATE fact_nav, dim_date, dim_scheme, dim_amc RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
def seeded_scheme(clean_db):
    """Seed one Equity scheme with a hand-computable NAV series; return its scheme_id.

    Series: 2025-01-01=100, 2025-06-01=120, 2025-12-01=90, 2026-01-01=110 (latest).
    Expected: 1Y return +10%, 1M return +22.22%, max drawdown -25%.
    """
    db.execute("INSERT INTO dim_amc (amc_name) VALUES ('Test AMC')")
    amc_id = db.query("SELECT amc_id FROM dim_amc WHERE amc_name='Test AMC'")[0]["amc_id"]
    db.execute(
        "INSERT INTO dim_scheme (scheme_code, amc_id, scheme_name, scheme_category, isin) "
        "VALUES (%s, %s, %s, %s, %s)",
        (900900, amc_id, "Test Equity Fund - Direct - Growth", "Equity", "INFTEST00001"),
    )
    scheme_id = db.query("SELECT scheme_id FROM dim_scheme WHERE scheme_code=900900")[0]["scheme_id"]

    db.execute(
        """
        INSERT INTO dim_date (nav_date, day_of_week, month, quarter, year, is_business_day)
        SELECT d,
               EXTRACT(DOW   FROM d)::int,
               EXTRACT(MONTH FROM d)::int,
               EXTRACT(QUARTER FROM d)::int,
               EXTRACT(YEAR  FROM d)::int,
               EXTRACT(ISODOW FROM d) < 6
        FROM (VALUES ('2025-01-01'::date), ('2025-06-01'::date),
                     ('2025-12-01'::date), ('2026-01-01'::date)) v(d)
        """
    )
    db.execute(
        """
        INSERT INTO fact_nav (scheme_id, nav_date, nav_value) VALUES
            (%(s)s, '2025-01-01', 100),
            (%(s)s, '2025-06-01', 120),
            (%(s)s, '2025-12-01', 90),
            (%(s)s, '2026-01-01', 110)
        """,
        {"s": scheme_id},
    )
    analytics.refresh_returns()
    return scheme_id


@pytest.fixture
def sample_records():
    """A tiny set of NavRecords for loader/idempotency tests."""
    from datetime import date

    return [
        NavRecord(900001, "INF0001", "Fund A - Growth", "Alpha MF", "Equity", 100.0, date(2026, 1, 1)),
        NavRecord(900001, "INF0001", "Fund A - Growth", "Alpha MF", "Equity", 101.0, date(2026, 1, 2)),
        NavRecord(900002, "INF0002", "Fund B - Growth", "Beta MF", "Debt", 50.0, date(2026, 1, 1)),
    ]
