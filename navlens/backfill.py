"""One-time historical backfill for a subset of schemes.

The AMFI daily file only carries the latest NAV, so the window-function analytics
(rolling returns, volatility, drawdown) need history. We pull ~2 years of history for a
small, category-balanced subset of growth-plan schemes from mfapi.in (a public,
AMFI-sourced JSON history API) and load it through the same loader the daily job uses.

Usage:
    python -m navlens.backfill              # pick subset from the DB universe, backfill it
    python -m navlens.backfill 119552 120437   # backfill explicit scheme codes
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

import requests

from . import db
from .config import BACKFILL_PER_CATEGORY, BACKFILL_YEARS, MFAPI_SCHEME_URL, coarse_category
from .ingest import NavRecord, load_records

_HEADERS = {"User-Agent": "NAVLens/0.1 (+https://github.com/SamBhojwani)"}


def select_subset(per_category: int = BACKFILL_PER_CATEGORY) -> list[int]:
    """Pick growth-plan direct schemes, up to `per_category` per category, from the universe.

    Relies on the daily AMFI ingest having populated dim_scheme first.
    """
    rows = db.query(
        """
        WITH ranked AS (
            SELECT scheme_code, scheme_category,
                   ROW_NUMBER() OVER (PARTITION BY scheme_category ORDER BY scheme_code) AS rn
            FROM dim_scheme
            WHERE scheme_name ILIKE '%%growth%%'
              AND scheme_name ILIKE '%%direct%%'
              AND scheme_category <> 'Other'
        )
        SELECT scheme_code FROM ranked WHERE rn <= %s ORDER BY scheme_category, scheme_code
        """,
        (per_category,),
    )
    return [r["scheme_code"] for r in rows]


def fetch_history(scheme_code: int, since: date) -> list[NavRecord]:
    """Fetch one scheme's NAV history (from `since`) as NavRecords."""
    resp = requests.get(MFAPI_SCHEME_URL.format(scheme_code=scheme_code), timeout=45, headers=_HEADERS)
    resp.raise_for_status()
    payload = resp.json()
    meta = payload.get("meta") or {}
    if not meta.get("fund_house"):
        return []

    amc_name = meta["fund_house"]
    category = coarse_category(meta.get("scheme_category") or meta.get("scheme_type") or "")
    scheme_name = meta.get("scheme_name", f"Scheme {scheme_code}")
    isin = meta.get("isin_growth") or meta.get("isin_div_reinvestment")

    records: list[NavRecord] = []
    for point in payload.get("data", []):
        try:
            nav_date = datetime.strptime(point["date"], "%d-%m-%Y").date()
            nav_value = float(point["nav"])
        except (KeyError, ValueError):
            continue
        if nav_date < since or nav_value <= 0:
            continue
        records.append(
            NavRecord(
                scheme_code=scheme_code,
                isin=isin,
                scheme_name=scheme_name,
                amc_name=amc_name,
                scheme_category=category,
                nav_value=nav_value,
                nav_date=nav_date,
            )
        )
    return records


def backfill(scheme_codes: list[int] | None = None, years: int = BACKFILL_YEARS) -> dict[str, int]:
    """Backfill history for the given (or auto-selected) scheme codes."""
    codes = scheme_codes or select_subset()
    if not codes:
        raise SystemExit(
            "No schemes to backfill. Run `python -m navlens.ingest` first to load the universe."
        )
    since = date.today() - timedelta(days=int(years * 365.25))

    all_records: list[NavRecord] = []
    ok = 0
    for code in codes:
        try:
            recs = fetch_history(code, since)
        except Exception as exc:  # noqa: BLE001 - one bad scheme shouldn't abort the run
            print(f"  ! scheme {code}: {exc}")
            continue
        if recs:
            ok += 1
            all_records.extend(recs)

    counts = load_records(all_records)
    counts["schemes_backfilled"] = ok
    counts["nav_points"] = len(all_records)
    return counts


if __name__ == "__main__":
    explicit = [int(a) for a in sys.argv[1:]] or None
    result = backfill(explicit)
    print(
        f"Backfilled {result['schemes_backfilled']} schemes | "
        f"{result['nav_points']} NAV points | new facts {result['facts_inserted']}"
    )
