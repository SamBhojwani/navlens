PY := ./.venv/bin/python

.PHONY: setup db schema ingest backfill refresh api dashboard test

setup:            ## create venv and install deps
	python3 -m venv .venv && $(PY) -m pip install -r requirements.txt

db:               ## start local Postgres (Docker)
	docker compose up -d

schema:           ## apply schema + views
	$(PY) -c "from navlens.db import run_sql_file as r; r('sql/01_schema.sql'); r('sql/02_views.sql')"

ingest:           ## load today's AMFI NAV file
	$(PY) -m navlens.ingest

backfill:         ## backfill ~2y history for the analytics subset
	$(PY) -m navlens.backfill

refresh:          ## refresh the materialized returns view
	$(PY) -m navlens.analytics

api:              ## run the FastAPI service
	./.venv/bin/uvicorn navlens.api:app --reload

dashboard:        ## run the Streamlit dashboard
	./.venv/bin/streamlit run dashboard/app.py

test:             ## run the test suite
	$(PY) -m pytest
