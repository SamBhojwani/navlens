"""Query helpers over the SQL views, plus materialized-view refresh.

The API and dashboard call these; they hold no analytics logic of their own -- every
number comes from the SQL views in sql/02_views.sql.
"""
from __future__ import annotations

from . import db


def refresh_returns() -> None:
    """Recompute the materialized returns view. Call after each ingest/backfill."""
    db.execute("REFRESH MATERIALIZED VIEW mv_scheme_returns")


def safe_refresh() -> None:
    """Refresh if the materialized view exists yet (no-op before views are applied)."""
    exists = db.query("SELECT to_regclass('public.mv_scheme_returns') AS r")[0]["r"]
    if exists:
        refresh_returns()


# --- read helpers used by the API / dashboard -------------------------------

def search_schemes(q: str | None = None, category: str | None = None,
                   amc: str | None = None, limit: int = 50) -> list[dict]:
    return db.query(
        """
        SELECT s.scheme_id, s.scheme_code, s.scheme_name, s.scheme_category, a.amc_name
        FROM dim_scheme s
        JOIN dim_amc a ON a.amc_id = s.amc_id
        WHERE (%(q)s     IS NULL OR s.scheme_name ILIKE '%%' || %(q)s || '%%')
          AND (%(cat)s   IS NULL OR s.scheme_category = %(cat)s)
          AND (%(amc)s   IS NULL OR a.amc_name = %(amc)s)
        ORDER BY s.scheme_name
        LIMIT %(limit)s
        """,
        {"q": q, "cat": category, "amc": amc, "limit": limit},
    )


def nav_history(scheme_id: int) -> list[dict]:
    return db.query(
        "SELECT nav_date, nav_value FROM fact_nav WHERE scheme_id = %s ORDER BY nav_date",
        (scheme_id,),
    )


def scheme_returns(scheme_id: int) -> dict | None:
    rows = db.query("SELECT * FROM mv_scheme_returns WHERE scheme_id = %s", (scheme_id,))
    return rows[0] if rows else None


def category_rankings(category: str, top: int = 10) -> dict[str, list[dict]]:
    rows = db.query(
        """
        SELECT scheme_id, scheme_code, scheme_name, amc_name, return_1y_pct,
               rank_in_category, funds_in_category
        FROM v_category_rankings
        WHERE scheme_category = %s
        ORDER BY rank_in_category
        """,
        (category,),
    )
    return {"top": rows[:top], "bottom": rows[-top:][::-1], "total": len(rows)}


def drawdown_series(scheme_id: int) -> list[dict]:
    return db.query(
        """
        SELECT nav_date, nav_value, running_peak, drawdown_pct
        FROM v_drawdown_series WHERE scheme_id = %s ORDER BY nav_date
        """,
        (scheme_id,),
    )


def rolling_volatility(scheme_id: int) -> list[dict]:
    return db.query(
        """
        SELECT nav_date, rolling_vol_ann_pct, obs_in_window
        FROM v_rolling_volatility WHERE scheme_id = %s ORDER BY nav_date
        """,
        (scheme_id,),
    )


def amc_rollup() -> list[dict]:
    return db.query(
        """
        SELECT amc_name, scheme_category, fund_count, avg_1y_return_pct
        FROM v_amc_rollup
        ORDER BY (amc_name = 'ALL AMCs') DESC, amc_name, scheme_category
        """
    )


def schemes_with_history(min_points: int = 30) -> list[dict]:
    """Schemes that have enough NAV history for the charts to be meaningful."""
    return db.query(
        """
        SELECT s.scheme_id, s.scheme_code, s.scheme_name, s.scheme_category, a.amc_name
        FROM dim_scheme s
        JOIN dim_amc a ON a.amc_id = s.amc_id
        JOIN (
            SELECT scheme_id FROM fact_nav GROUP BY scheme_id HAVING COUNT(*) >= %s
        ) h ON h.scheme_id = s.scheme_id
        ORDER BY s.scheme_category, s.scheme_name
        """,
        (min_points,),
    )


def categories() -> list[str]:
    rows = db.query(
        "SELECT DISTINCT scheme_category FROM dim_scheme WHERE scheme_category <> 'Other' ORDER BY 1"
    )
    return [r["scheme_category"] for r in rows]


if __name__ == "__main__":
    safe_refresh()
    print("mv_scheme_returns refreshed")
