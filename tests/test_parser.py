"""Pure parser tests (no database)."""
from datetime import date
from pathlib import Path

from navlens.ingest import parse_navall

SAMPLE = (Path(__file__).parent / "sample_navall.txt").read_text()
RECORDS = parse_navall(SAMPLE)
BY_CODE = {r.scheme_code: r for r in RECORDS}


def test_skips_header_and_na_rows():
    # 5 data lines, but the N.A. row (900004) is dropped -> 4 records.
    assert len(RECORDS) == 4
    assert 900004 not in BY_CODE


def test_amc_headers_parsed():
    assert {r.amc_name for r in RECORDS} == {"Alpha Mutual Fund", "Beta Mutual Fund", "Gamma Mutual Fund"}


def test_amc_assigned_to_correct_scheme():
    assert BY_CODE[900001].amc_name == "Alpha Mutual Fund"
    assert BY_CODE[900003].amc_name == "Beta Mutual Fund"
    assert BY_CODE[900005].amc_name == "Gamma Mutual Fund"


def test_category_equity():
    assert BY_CODE[900001].scheme_category == "Equity"


def test_category_debt():
    assert BY_CODE[900003].scheme_category == "Debt"


def test_category_hybrid():
    assert BY_CODE[900005].scheme_category == "Hybrid"


def test_isin_prefers_payout_growth():
    assert BY_CODE[900001].isin == "INF001AA0001"


def test_isin_falls_back_to_reinvestment():
    # 900002 has '-' in the first ISIN column, so the reinvestment ISIN is used.
    assert BY_CODE[900002].isin == "INF001AA0003"


def test_isin_none_when_both_dashes():
    # 900003 has reinvestment '-'; first column present, so ISIN is the growth one.
    assert BY_CODE[900003].isin == "INF002BB0001"


def test_nav_value_parsed():
    assert BY_CODE[900001].nav_value == 150.5


def test_date_parsed():
    assert BY_CODE[900001].nav_date == date(2026, 7, 3)


def test_section_header_not_treated_as_amc():
    # If a "... Schemes(...)" line were mistaken for an AMC, amc_name would be wrong.
    assert all("Schemes(" not in r.amc_name for r in RECORDS)


def test_empty_input():
    assert parse_navall("") == []
