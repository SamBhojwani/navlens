"""Loader and idempotency tests (require the test database)."""
from datetime import date

from navlens import db
from navlens.ingest import NavRecord, load_records


def _fact_count() -> int:
    return db.query("SELECT COUNT(*) AS c FROM fact_nav")[0]["c"]


def test_load_inserts_expected_rows(clean_db, sample_records):
    counts = load_records(sample_records)
    assert counts["facts_inserted"] == 3
    assert db.query("SELECT COUNT(*) AS c FROM dim_amc")[0]["c"] == 2
    assert db.query("SELECT COUNT(*) AS c FROM dim_scheme")[0]["c"] == 2
    assert _fact_count() == 3


def test_reload_is_idempotent(clean_db, sample_records):
    load_records(sample_records)
    first = _fact_count()
    counts = load_records(sample_records)  # same data again
    assert counts["facts_inserted"] == 0
    assert _fact_count() == first


def test_dedup_within_single_batch(clean_db):
    # Two records with the same (scheme, date) collapse to one fact row.
    dup = [
        NavRecord(900010, "INF", "Dup Fund", "AMC", "Equity", 10.0, date(2026, 1, 1)),
        NavRecord(900010, "INF", "Dup Fund", "AMC", "Equity", 10.0, date(2026, 1, 1)),
    ]
    load_records(dup)
    assert _fact_count() == 1


def test_scheme_attributes_upsert(clean_db):
    load_records([NavRecord(900011, "INF", "Old Name", "AMC", "Equity", 10.0, date(2026, 1, 1))])
    load_records([NavRecord(900011, "INF", "New Name", "AMC", "Debt", 11.0, date(2026, 1, 2))])
    row = db.query("SELECT scheme_name, scheme_category FROM dim_scheme WHERE scheme_code=900011")[0]
    assert row["scheme_name"] == "New Name"
    assert row["scheme_category"] == "Debt"


def test_empty_load_noop(clean_db):
    counts = load_records([])
    assert counts["facts_inserted"] == 0
    assert _fact_count() == 0
