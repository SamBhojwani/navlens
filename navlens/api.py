"""FastAPI service: a thin read layer over the SQL views.

It computes nothing itself; every endpoint delegates to navlens.analytics, which reads
the views in sql/02_views.sql. Run with:  uvicorn navlens.api:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import analytics

app = FastAPI(
    title="NAVLens API",
    version="0.1.0",
    description="Mutual fund NAV analytics computed in SQL (returns, volatility, drawdown, rankings).",
)

# Open CORS so the Streamlit dashboard can call the API when hosted separately.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/categories")
def list_categories() -> list[str]:
    return analytics.categories()


@app.get("/schemes")
def list_schemes(
    q: str | None = Query(None, description="Substring match on scheme name"),
    category: str | None = None,
    amc: str | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    return analytics.search_schemes(q=q, category=category, amc=amc, limit=limit)


@app.get("/schemes/{scheme_id}/nav")
def scheme_nav(scheme_id: int) -> dict:
    history = analytics.nav_history(scheme_id)
    if not history:
        raise HTTPException(status_code=404, detail="No NAV history for that scheme_id")
    return {"scheme_id": scheme_id, "points": history}


@app.get("/schemes/{scheme_id}/returns")
def scheme_returns(scheme_id: int) -> dict:
    result = analytics.scheme_returns(scheme_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No returns for that scheme_id (needs history)")
    return result


@app.get("/schemes/{scheme_id}/drawdown")
def scheme_drawdown(scheme_id: int) -> dict:
    series = analytics.drawdown_series(scheme_id)
    if not series:
        raise HTTPException(status_code=404, detail="No drawdown series for that scheme_id")
    worst = min((p["drawdown_pct"] for p in series if p["drawdown_pct"] is not None), default=None)
    return {"scheme_id": scheme_id, "max_drawdown_pct": worst, "series": series}


@app.get("/schemes/{scheme_id}/volatility")
def scheme_volatility(scheme_id: int) -> dict:
    series = analytics.rolling_volatility(scheme_id)
    if not series:
        raise HTTPException(status_code=404, detail="No volatility series for that scheme_id")
    return {"scheme_id": scheme_id, "series": series}


@app.get("/categories/{category}/rankings")
def category_rankings(category: str, top: int = Query(10, ge=1, le=50)) -> dict:
    result = analytics.category_rankings(category, top=top)
    if result["total"] == 0:
        raise HTTPException(status_code=404, detail="No ranked funds in that category")
    result["category"] = category
    return result


@app.get("/amcs/summary")
def amcs_summary() -> list[dict]:
    return analytics.amc_rollup()
