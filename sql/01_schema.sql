-- NAVLens dimensional schema (star schema).
-- Three dimensions (AMC, scheme, date) and one NAV fact table.
-- Designed so every analytic query is a clean join over these tables.

-- Asset Management Company (the fund house), e.g. "Axis Mutual Fund".
CREATE TABLE IF NOT EXISTS dim_amc (
    amc_id   SERIAL PRIMARY KEY,
    amc_name TEXT NOT NULL UNIQUE
);

-- A single scheme/plan, identified by its AMFI scheme code.
CREATE TABLE IF NOT EXISTS dim_scheme (
    scheme_id       SERIAL PRIMARY KEY,
    scheme_code     INTEGER NOT NULL UNIQUE,          -- AMFI scheme code
    amc_id          INTEGER NOT NULL REFERENCES dim_amc(amc_id),
    scheme_name     TEXT NOT NULL,
    scheme_category TEXT,                             -- coarse bucket: Equity/Debt/Hybrid/...
    isin            TEXT
);

-- Calendar dimension. One row per NAV date we have seen.
CREATE TABLE IF NOT EXISTS dim_date (
    nav_date        DATE PRIMARY KEY,
    day_of_week     INTEGER NOT NULL,                 -- 0=Sunday ... 6=Saturday (EXTRACT DOW)
    month           INTEGER NOT NULL,
    quarter         INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    is_business_day BOOLEAN NOT NULL                  -- Mon-Fri (no holiday calendar)
);

-- The fact: one NAV value per scheme per date.
-- Composite PK gives natural dedup; ON CONFLICT DO NOTHING makes ingestion idempotent.
CREATE TABLE IF NOT EXISTS fact_nav (
    scheme_id  INTEGER NOT NULL REFERENCES dim_scheme(scheme_id),
    nav_date   DATE    NOT NULL REFERENCES dim_date(nav_date),
    nav_value  NUMERIC(18,4) NOT NULL,
    PRIMARY KEY (scheme_id, nav_date)
);

CREATE INDEX IF NOT EXISTS idx_fact_nav_scheme_date ON fact_nav (scheme_id, nav_date);
CREATE INDEX IF NOT EXISTS idx_scheme_category      ON dim_scheme (scheme_category);
CREATE INDEX IF NOT EXISTS idx_scheme_amc           ON dim_scheme (amc_id);
