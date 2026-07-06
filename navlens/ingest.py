"""Ingest the AMFI daily NAV flat file into the star schema.

Live source of truth. The parser is pure (text in, records out) so it is unit-tested
without a database; the loaders are idempotent (ON CONFLICT DO NOTHING / DO UPDATE),
so re-running the same file inserts no duplicate NAV rows.

Usage:
    python -m navlens.ingest                 # download today's file and load it
    python -m navlens.ingest path/to/file.txt  # load a local file (e.g. a fixture)
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, datetime

import requests

from . import db
from .config import AMFI_NAVALL_URL, coarse_category

# A header line for a scheme-type section, e.g. "Open Ended Schemes(Equity Scheme - Large Cap Fund)".
_SECTION_RE = re.compile(r"scheme", re.IGNORECASE)


@dataclass(frozen=True)
class NavRecord:
    scheme_code: int
    isin: str | None
    scheme_name: str
    amc_name: str
    scheme_category: str
    nav_value: float
    nav_date: date


def _parse_nav(value: str) -> float | None:
    value = value.strip()
    if value in ("", "-", "N.A.", "NA", "N/A"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def parse_navall(text: str) -> list[NavRecord]:
    """Parse AMFI NAVAll text into NavRecords.

    The file interleaves three line kinds between data blocks:
      * a section header   -> "... Schemes(<category text>)"  (sets current category)
      * a fund-house header -> "Axis Mutual Fund"             (sets current AMC)
      * a data row          -> six semicolon-separated fields
    """
    records: list[NavRecord] = []
    current_amc: str | None = None
    current_section: str = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Scheme Code"):  # column header
            continue

        if ";" in line:
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 6:
                continue
            code_s, isin1, isin2, name, nav_s, date_s = parts[:6]
            try:
                scheme_code = int(code_s)
            except ValueError:
                continue
            nav_value = _parse_nav(nav_s)
            nav_date = _parse_date(date_s)
            if nav_value is None or nav_date is None or not name:
                continue
            isin = isin1 if isin1 and isin1 != "-" else (isin2 if isin2 and isin2 != "-" else None)
            if current_amc is None:
                continue  # data before any AMC header; skip defensively
            records.append(
                NavRecord(
                    scheme_code=scheme_code,
                    isin=isin,
                    scheme_name=name,
                    amc_name=current_amc,
                    scheme_category=coarse_category(current_section),
                    nav_value=nav_value,
                    nav_date=nav_date,
                )
            )
        else:
            # Non-data line: a section header if it mentions "scheme" and has "(", else an AMC.
            if _SECTION_RE.search(line) and "(" in line:
                current_section = line
            else:
                current_amc = line

    return records


def fetch_navall_text(attempts: int = 5, backoff: float = 4.0) -> str:
    """Download today's AMFI NAVAll flat file, retrying transient 5xx/network errors.

    AMFI's edge occasionally returns 503 under load; a few backed-off retries make the
    daily job reliable without any extra infrastructure.
    """
    import time

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/plain, */*",
    }
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(AMFI_NAVALL_URL, timeout=90, allow_redirects=True, headers=headers)
            if resp.status_code == 200 and "Scheme Code" in resp.text[:200]:
                return resp.text
            resp.raise_for_status()
            last_err = RuntimeError(f"unexpected body (status {resp.status_code})")
        except Exception as exc:  # noqa: BLE001 - retry any transient failure
            last_err = exc
        if attempt < attempts:
            time.sleep(backoff * attempt)
    raise RuntimeError(f"AMFI fetch failed after {attempts} attempts: {last_err}")


# --- Loaders (idempotent) ---------------------------------------------------

def _date_attrs(d: date) -> tuple[int, int, int, int, bool]:
    dow = d.isoweekday() % 7            # Postgres EXTRACT(DOW): Sunday=0 .. Saturday=6
    quarter = (d.month - 1) // 3 + 1
    is_business = d.weekday() < 5       # Mon-Fri (no holiday calendar)
    return dow, d.month, quarter, d.year, is_business


def load_records(records: list[NavRecord]) -> dict[str, int]:
    """Upsert AMCs, schemes and dates, then insert NAV facts. Returns counts."""
    if not records:
        return {"amcs": 0, "schemes": 0, "dates": 0, "facts_inserted": 0}

    # 1) AMCs
    amc_names = sorted({r.amc_name for r in records})
    db.insert_batch(
        "INSERT INTO dim_amc (amc_name) VALUES %s ON CONFLICT (amc_name) DO NOTHING",
        [(n,) for n in amc_names],
    )
    amc_map = {r["amc_name"]: r["amc_id"] for r in db.query("SELECT amc_id, amc_name FROM dim_amc")}

    # 2) Schemes (dedup by scheme_code; last occurrence wins for attributes)
    scheme_rows = {}
    for r in records:
        scheme_rows[r.scheme_code] = (
            r.scheme_code, amc_map[r.amc_name], r.scheme_name, r.scheme_category, r.isin,
        )
    db.insert_batch(
        """INSERT INTO dim_scheme (scheme_code, amc_id, scheme_name, scheme_category, isin)
           VALUES %s
           ON CONFLICT (scheme_code) DO UPDATE SET
               amc_id          = EXCLUDED.amc_id,
               scheme_name     = EXCLUDED.scheme_name,
               scheme_category = EXCLUDED.scheme_category,
               isin            = EXCLUDED.isin""",
        list(scheme_rows.values()),
    )
    scheme_map = {r["scheme_code"]: r["scheme_id"] for r in db.query("SELECT scheme_id, scheme_code FROM dim_scheme")}

    # 3) Dates
    dates = sorted({r.nav_date for r in records})
    db.insert_batch(
        """INSERT INTO dim_date (nav_date, day_of_week, month, quarter, year, is_business_day)
           VALUES %s ON CONFLICT (nav_date) DO NOTHING""",
        [(d, *_date_attrs(d)) for d in dates],
    )

    # 4) Facts (idempotent on the composite PK)
    before = db.query("SELECT COUNT(*) AS c FROM fact_nav")[0]["c"]
    fact_rows = [(scheme_map[r.scheme_code], r.nav_date, r.nav_value) for r in records]
    db.insert_batch(
        "INSERT INTO fact_nav (scheme_id, nav_date, nav_value) VALUES %s "
        "ON CONFLICT (scheme_id, nav_date) DO NOTHING",
        fact_rows,
    )
    after = db.query("SELECT COUNT(*) AS c FROM fact_nav")[0]["c"]

    return {
        "amcs": len(amc_names),
        "schemes": len(scheme_rows),
        "dates": len(dates),
        "facts_inserted": after - before,
    }


def ingest(source: str | None = None) -> dict[str, int]:
    """Load from a local file path if given, otherwise download today's AMFI file."""
    if source:
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = fetch_navall_text()
    records = parse_navall(text)
    counts = load_records(records)
    counts["records_parsed"] = len(records)
    return counts


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = ingest(arg)
    print(
        f"Parsed {result['records_parsed']} rows | "
        f"AMCs {result['amcs']} | schemes {result['schemes']} | "
        f"dates {result['dates']} | new NAV facts {result['facts_inserted']}"
    )
