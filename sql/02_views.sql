-- NAVLens analytics, computed entirely in SQL.
-- These views ARE the project: rolling returns, volatility, rankings and drawdown
-- expressed with window functions, CTEs and aggregations. No metric is computed in Python.

-- 1) Daily simple returns per scheme (feeds volatility).
--    LAG() pulls the previous available NAV in date order; NULLIF guards divide-by-zero.
CREATE OR REPLACE VIEW v_daily_returns AS
SELECT
    scheme_id,
    nav_date,
    nav_value,
    nav_value / NULLIF(LAG(nav_value) OVER (PARTITION BY scheme_id ORDER BY nav_date), 0) - 1
        AS daily_return
FROM fact_nav;


-- 2) Rolling returns (1M/3M/6M/1Y) per scheme, materialized because the rankings and
--    AMC rollup below both build on it and it does correlated "as-of" lookups.
--    For each scheme's latest NAV we fetch the most recent NAV on-or-before the date N
--    periods earlier (calendar-correct across weekends/holidays) via LATERAL subqueries.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_scheme_returns AS
WITH latest AS (
    SELECT scheme_id, MAX(nav_date) AS cur_date
    FROM fact_nav
    GROUP BY scheme_id
),
cur AS (
    SELECT f.scheme_id, f.nav_date AS cur_date, f.nav_value AS cur_nav
    FROM fact_nav f
    JOIN latest l ON l.scheme_id = f.scheme_id AND l.cur_date = f.nav_date
)
SELECT
    c.scheme_id,
    c.cur_date,
    c.cur_nav,
    ROUND((c.cur_nav / NULLIF(n1.nav_value, 0)  - 1) * 100, 2) AS return_1m_pct,
    ROUND((c.cur_nav / NULLIF(n3.nav_value, 0)  - 1) * 100, 2) AS return_3m_pct,
    ROUND((c.cur_nav / NULLIF(n6.nav_value, 0)  - 1) * 100, 2) AS return_6m_pct,
    ROUND((c.cur_nav / NULLIF(n12.nav_value, 0) - 1) * 100, 2) AS return_1y_pct
FROM cur c
LEFT JOIN LATERAL (
    SELECT nav_value FROM fact_nav p
    WHERE p.scheme_id = c.scheme_id AND p.nav_date <= c.cur_date - INTERVAL '1 month'
    ORDER BY p.nav_date DESC LIMIT 1
) n1 ON TRUE
LEFT JOIN LATERAL (
    SELECT nav_value FROM fact_nav p
    WHERE p.scheme_id = c.scheme_id AND p.nav_date <= c.cur_date - INTERVAL '3 months'
    ORDER BY p.nav_date DESC LIMIT 1
) n3 ON TRUE
LEFT JOIN LATERAL (
    SELECT nav_value FROM fact_nav p
    WHERE p.scheme_id = c.scheme_id AND p.nav_date <= c.cur_date - INTERVAL '6 months'
    ORDER BY p.nav_date DESC LIMIT 1
) n6 ON TRUE
LEFT JOIN LATERAL (
    SELECT nav_value FROM fact_nav p
    WHERE p.scheme_id = c.scheme_id AND p.nav_date <= c.cur_date - INTERVAL '1 year'
    ORDER BY p.nav_date DESC LIMIT 1
) n12 ON TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_scheme_returns ON mv_scheme_returns (scheme_id);


-- 3) Rolling annualized volatility: STDDEV() as a window function over daily returns,
--    across a trailing 63-trading-day window, annualized by sqrt(252).
CREATE OR REPLACE VIEW v_rolling_volatility AS
SELECT
    scheme_id,
    nav_date,
    ROUND(((STDDEV(daily_return) OVER w) * SQRT(252) * 100)::numeric, 2) AS rolling_vol_ann_pct,
    COUNT(daily_return) OVER w AS obs_in_window
FROM v_daily_returns
WHERE daily_return IS NOT NULL
WINDOW w AS (
    PARTITION BY scheme_id ORDER BY nav_date
    ROWS BETWEEN 62 PRECEDING AND CURRENT ROW
);


-- 4) Drawdown series: running peak via MAX() OVER an expanding window, then the
--    percentage decline from that peak.
CREATE OR REPLACE VIEW v_drawdown_series AS
SELECT
    scheme_id,
    nav_date,
    nav_value,
    MAX(nav_value) OVER (
        PARTITION BY scheme_id ORDER BY nav_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_peak,
    ROUND((nav_value / NULLIF(MAX(nav_value) OVER (
        PARTITION BY scheme_id ORDER BY nav_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ), 0) - 1) * 100, 2) AS drawdown_pct
FROM fact_nav;

-- Maximum drawdown per scheme = the deepest point of the series.
CREATE OR REPLACE VIEW v_max_drawdown AS
SELECT scheme_id, MIN(drawdown_pct) AS max_drawdown_pct
FROM v_drawdown_series
GROUP BY scheme_id;


-- 5) Category rankings: rank funds within each category by trailing 1Y return.
CREATE OR REPLACE VIEW v_category_rankings AS
SELECT
    s.scheme_category,
    s.scheme_id,
    s.scheme_code,
    s.scheme_name,
    a.amc_name,
    r.return_1y_pct,
    RANK() OVER (PARTITION BY s.scheme_category ORDER BY r.return_1y_pct DESC) AS rank_in_category,
    COUNT(*)  OVER (PARTITION BY s.scheme_category)                           AS funds_in_category
FROM mv_scheme_returns r
JOIN dim_scheme s ON s.scheme_id = r.scheme_id
JOIN dim_amc    a ON a.amc_id    = s.amc_id
WHERE r.return_1y_pct IS NOT NULL;


-- 6) Multi-step CTE analysis: for each AMC, its single best equity fund by 1Y return,
--    considering only funds with a meaningful history (>= 200 NAV observations).
--    Stages: count observations -> filter eligible equity funds -> rank within AMC -> keep #1.
CREATE OR REPLACE VIEW v_amc_top_equity AS
WITH obs AS (
    SELECT scheme_id, COUNT(*) AS n_obs
    FROM fact_nav
    GROUP BY scheme_id
),
eligible AS (
    SELECT s.scheme_id, s.amc_id, s.scheme_name
    FROM dim_scheme s
    JOIN obs o ON o.scheme_id = s.scheme_id
    WHERE s.scheme_category = 'Equity' AND o.n_obs >= 200
),
ranked AS (
    SELECT
        e.amc_id,
        e.scheme_name,
        r.return_1y_pct,
        RANK() OVER (PARTITION BY e.amc_id ORDER BY r.return_1y_pct DESC) AS rk
    FROM eligible e
    JOIN mv_scheme_returns r ON r.scheme_id = e.scheme_id
    WHERE r.return_1y_pct IS NOT NULL
)
SELECT a.amc_name, ranked.scheme_name, ranked.return_1y_pct
FROM ranked
JOIN dim_amc a ON a.amc_id = ranked.amc_id
WHERE ranked.rk = 1
ORDER BY ranked.return_1y_pct DESC;


-- 6b) Bonus: AMC-level rollup with subtotals and a grand total via ROLLUP.
CREATE OR REPLACE VIEW v_amc_rollup AS
SELECT
    COALESCE(a.amc_name, 'ALL AMCs')            AS amc_name,
    COALESCE(s.scheme_category, 'ALL CATEGORIES') AS scheme_category,
    COUNT(DISTINCT s.scheme_id)                 AS fund_count,
    ROUND(AVG(r.return_1y_pct), 2)              AS avg_1y_return_pct
FROM dim_scheme s
JOIN dim_amc a ON a.amc_id = s.amc_id
LEFT JOIN mv_scheme_returns r ON r.scheme_id = s.scheme_id
GROUP BY ROLLUP (a.amc_name, s.scheme_category);
