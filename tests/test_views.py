"""SQL view correctness on a seeded, hand-computable dataset (require test database).

Seeded series: 100 -> 120 -> 90 -> 110 (latest).
"""
import pytest

from navlens import db


def test_rolling_return_1y(seeded_scheme):
    row = db.query("SELECT return_1y_pct FROM mv_scheme_returns WHERE scheme_id=%s", (seeded_scheme,))[0]
    assert float(row["return_1y_pct"]) == pytest.approx(10.0)  # 110/100 - 1


def test_rolling_return_1m(seeded_scheme):
    row = db.query("SELECT return_1m_pct FROM mv_scheme_returns WHERE scheme_id=%s", (seeded_scheme,))[0]
    assert float(row["return_1m_pct"]) == pytest.approx(22.22, abs=0.01)  # 110/90 - 1


def test_rolling_return_6m(seeded_scheme):
    # 6 months before 2026-01-01 is 2025-07-01; latest NAV on-or-before is 2025-06-01 (120).
    row = db.query("SELECT return_6m_pct FROM mv_scheme_returns WHERE scheme_id=%s", (seeded_scheme,))[0]
    assert float(row["return_6m_pct"]) == pytest.approx(-8.33, abs=0.01)  # 110/120 - 1


def test_max_drawdown(seeded_scheme):
    row = db.query("SELECT max_drawdown_pct FROM v_max_drawdown WHERE scheme_id=%s", (seeded_scheme,))[0]
    assert float(row["max_drawdown_pct"]) == pytest.approx(-25.0)  # trough 90 vs peak 120


def test_daily_return_latest(seeded_scheme):
    row = db.query(
        "SELECT daily_return FROM v_daily_returns WHERE scheme_id=%s AND nav_date='2026-01-01'",
        (seeded_scheme,),
    )[0]
    assert float(row["daily_return"]) == pytest.approx(0.2222, abs=0.0001)  # 110/90 - 1


def test_running_peak_monotonic(seeded_scheme):
    peaks = [
        float(r["running_peak"])
        for r in db.query(
            "SELECT running_peak FROM v_drawdown_series WHERE scheme_id=%s ORDER BY nav_date",
            (seeded_scheme,),
        )
    ]
    assert peaks == sorted(peaks)  # running peak never decreases
    assert peaks[-1] == 120.0


def test_category_ranking_lists_seeded_scheme(seeded_scheme):
    rows = db.query(
        "SELECT scheme_id, rank_in_category FROM v_category_rankings WHERE scheme_category='Equity'"
    )
    assert any(r["scheme_id"] == seeded_scheme and r["rank_in_category"] == 1 for r in rows)
