# Heimdall Healthcare Threat Dashboard

Heimdall is a local-first analyst dashboard for monitoring healthcare-industry
news and assessing potential business impact for Third Horizon. It pulls Yahoo
Finance news through `yfinance`, stores articles in SQLite, runs deterministic
local assessment agents, and serves a responsive dashboard at
`http://127.0.0.1:8000`.

No paid AI API is required.

## Features

- Scheduled and manual news refreshes from configurable healthcare tickers.
- SQLite-backed article storage, deduplication, threat assessments, notes, and
  refresh history.
- Deterministic local agents that produce threat score, rationale, confidence,
  affected business areas, detected signals, risk categories, and recommended
  analyst action.
- Dashboard filters for ticker, threat score, business area, source, date
  range, full-text search, reviewed status, and sort order.
- High-priority and recently added sections.
- Article detail panel with original URL, normalized summary, agent rationale,
  signals, risk categories, reviewed status, and analyst notes.
- Analytics cards and breakdowns for volume, high threats, average score,
  affected business areas, active tickers, and daily trend.
- Ticker management and refresh/lookback configuration from the UI.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Configuration

Environment variables are used as startup defaults. Values persisted in SQLite
through the UI or `/api/config` override these at runtime.

```bash
DATABASE_PATH=./heimdall.db
NEWS_REFRESH_MINUTES=60
NEWS_LOOKBACK_HOURS=72
HEALTHCARE_TICKERS=UNH,CVS,ELV,HUM,CI,CNC,MOH,HCA,THC,UHS,PFE,JNJ,MRK,ABBV,MDT,ISRG
```

Tracked tickers are seeded from `HEALTHCARE_TICKERS` when the database is first
created. After that, use the dashboard or ticker API to add, disable, or delete
symbols.

## API

- `GET /api/dashboard` returns dashboard rows and high-priority/recent sections.
  Query parameters: `ticker`, `min_score`, `area`, `source`, `date_from`,
  `date_to`, `search`, `reviewed`, `sort`.
- `GET /api/articles` returns filtered article rows with assessments.
- `GET /api/articles/{id}` returns one article and its assessment.
- `PATCH /api/articles/{id}` updates `reviewed` and `analyst_notes`.
- `POST /api/refresh` starts an immediate refresh. Concurrent refreshes are
  serialized by the app.
- `GET /api/refresh-runs` returns recent refresh history.
- `GET /api/analytics` returns summary cards and aggregate breakdowns.
- `GET /api/tickers` lists tracked tickers.
- `POST /api/tickers` adds or re-enables a ticker.
- `PATCH /api/tickers/{id}` updates ticker symbol or enabled state.
- `DELETE /api/tickers/{id}` deletes a ticker.
- `GET /api/config` returns runtime configuration and business areas.
- `PATCH /api/config` updates `refresh_minutes` and `lookback_hours`.
- `GET /api/health` returns scheduler status.

## Database And Migrations

The app uses safe startup migrations in `app/storage.py`. Existing SQLite data
is preserved. New columns are added with nullable/default values, and these
tables are created when absent:

- `articles`
- `assessments`
- `tickers`
- `config`
- `business_areas`
- `refresh_runs`

Indexes are created for common dashboard queries, including article date,
ticker, reviewed status, threat score, affected area, and risk category.

## Tests

```bash
. .venv/bin/activate
python -m unittest
```

The tests cover article normalization, deduplication, threat scoring, affected
area/risk category detection, refresh-run tracking, ticker configuration,
startup migration behavior, and API endpoints.

## Troubleshooting

- If Yahoo Finance is unreachable or rate-limited, the refresh run records the
  error and the app falls back gracefully when no articles are available.
- If port `8000` is already in use, run `uvicorn app.main:app --reload --port 8001`.
- If dependencies fail on a very new Python version, recreate `.venv` and rerun
  `pip install -r requirements.txt`; the requirements use modern compatibility
  floors instead of old native-extension pins.
- Delete `heimdall.db` only when you intentionally want a fresh local database.

