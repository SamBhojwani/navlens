"""Central configuration and the scheme-category mapping.

Everything reads a single DATABASE_URL so local and production differ only by env var.
"""
import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://navlens:navlens@localhost:5433/navlens",
)

# AMFI daily flat file (live ingestion). Source of truth for the latest NAV.
AMFI_NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"

# Public AMFI-sourced per-scheme history API (one-time backfill only).
MFAPI_SCHEME_URL = "https://api.mfapi.in/mf/{scheme_code}"

# Backfill controls (kept small on purpose: this is a subset, not the whole market).
BACKFILL_YEARS = 2            # how far back to load history for the subset
BACKFILL_PER_CATEGORY = 15    # growth-plan schemes to backfill per category


def coarse_category(text: str) -> str:
    """Map AMFI's granular scheme-type text to a coarse, rankable bucket.

    The AMFI file groups schemes under headers like
    "Open Ended Schemes(Debt Scheme - Banking and PSU Fund)"; we bucket those into
    a handful of categories so "rank funds within a category" is meaningful.
    Order matters: more specific buckets are checked before the broad Debt catch-all.
    """
    t = (text or "").lower()
    if "solution" in t:
        return "Solution Oriented"
    if "index" in t or "etf" in t or "exchange traded" in t:
        return "Index/ETF"
    if "fund of funds" in t or "fof" in t:
        return "Fund of Funds"
    if "hybrid" in t or "balanced" in t:
        return "Hybrid"
    if "elss" in t or "equity" in t:
        return "Equity"
    debt_markers = (
        "debt", "gilt", "liquid", "money market", "bond", "psu", "duration",
        "credit risk", "corporate", "floater", "overnight", "banking",
    )
    if any(m in t for m in debt_markers):
        return "Debt"
    return "Other"
