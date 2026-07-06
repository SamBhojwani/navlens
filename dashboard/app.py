"""NAVLens Streamlit dashboard.

Surfaces the SQL analytics: NAV history, rolling returns, drawdown and a category
leaderboard. It reads the same views the API does (via navlens.analytics); it computes
nothing itself. Run with:  streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

# Make the navlens package importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from navlens import analytics

st.set_page_config(page_title="NAVLens", page_icon="📈", layout="wide")


@st.cache_data(ttl=600)
def load_schemes() -> pd.DataFrame:
    return pd.DataFrame(analytics.schemes_with_history())


@st.cache_data(ttl=600)
def load_nav(scheme_id: int) -> pd.DataFrame:
    df = pd.DataFrame(analytics.nav_history(scheme_id))
    if not df.empty:
        df["nav_date"] = pd.to_datetime(df["nav_date"])
        df["nav_value"] = df["nav_value"].astype(float)
    return df


@st.cache_data(ttl=600)
def load_drawdown(scheme_id: int) -> pd.DataFrame:
    df = pd.DataFrame(analytics.drawdown_series(scheme_id))
    if not df.empty:
        df["nav_date"] = pd.to_datetime(df["nav_date"])
        df["drawdown_pct"] = df["drawdown_pct"].astype(float)
    return df


@st.cache_data(ttl=600)
def load_returns(scheme_id: int) -> dict | None:
    return analytics.scheme_returns(scheme_id)


@st.cache_data(ttl=600)
def load_rankings(category: str) -> dict:
    return analytics.category_rankings(category, top=10)


st.title("📈 NAVLens")
st.caption("Indian mutual fund NAV analytics, computed entirely in SQL (returns, volatility, drawdown, rankings).")

schemes = load_schemes()
if schemes.empty:
    st.warning("No schemes with history yet. Run `python -m navlens.ingest` then `python -m navlens.backfill`.")
    st.stop()

# --- Sidebar: pick a category, then a scheme ---
with st.sidebar:
    st.header("Select a fund")
    cats = sorted(schemes["scheme_category"].unique())
    category = st.selectbox("Category", cats, index=cats.index("Equity") if "Equity" in cats else 0)
    subset = schemes[schemes["scheme_category"] == category]
    label_to_id = dict(zip(subset["scheme_name"], subset["scheme_id"]))
    scheme_name = st.selectbox("Scheme", list(label_to_id.keys()))
    scheme_id = int(label_to_id[scheme_name])
    amc = subset.loc[subset["scheme_id"] == scheme_id, "amc_name"].iloc[0]
    st.write(f"**AMC:** {amc}")

st.subheader(scheme_name)

# --- Rolling returns as headline metrics ---
returns = load_returns(scheme_id)
cols = st.columns(4)
labels = [("1M", "return_1m_pct"), ("3M", "return_3m_pct"), ("6M", "return_6m_pct"), ("1Y", "return_1y_pct")]
for col, (label, key) in zip(cols, labels):
    val = returns.get(key) if returns else None
    col.metric(f"{label} return", f"{float(val):.2f}%" if val is not None else "n/a")

# --- NAV history + drawdown charts ---
left, right = st.columns(2)
with left:
    st.markdown("**NAV history**")
    nav = load_nav(scheme_id)
    fig = px.line(nav, x="nav_date", y="nav_value", labels={"nav_date": "", "nav_value": "NAV"})
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

with right:
    dd = load_drawdown(scheme_id)
    worst = dd["drawdown_pct"].min() if not dd.empty else None
    st.markdown(f"**Drawdown from running peak**  (max: {worst:.2f}%)" if worst is not None else "**Drawdown**")
    fig = px.area(dd, x="nav_date", y="drawdown_pct", labels={"nav_date": "", "drawdown_pct": "Drawdown %"})
    fig.update_traces(line_color="#c0392b", fillcolor="rgba(192,57,43,0.2)")
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

# --- Category leaderboard ---
st.markdown(f"### {category} leaderboard — top 10 by 1-year return")
board = load_rankings(category)
if board["top"]:
    tbl = pd.DataFrame(board["top"])[["rank_in_category", "scheme_name", "amc_name", "return_1y_pct"]]
    tbl.columns = ["Rank", "Scheme", "AMC", "1Y return %"]
    st.dataframe(tbl, hide_index=True, use_container_width=True)
    st.caption(f"{board['total']} funds ranked in {category}.")
else:
    st.info("No ranked funds in this category yet.")
