# Heimdall Healthcare Threat Dashboard

A small web application that periodically pulls healthcare industry news from
Yahoo Finance via `yfinance`, assesses business threats for Thirs Horizon
Strategies, and renders a live dashboard.

## What It Does

- Pulls headline news from a configurable set of healthcare tickers.
- Runs scheduled refreshes in the background.
- Stores normalized articles and threat assessments in SQLite.
- Scores threats from `1` to `5`.
- Identifies which parts of Thirs Horizon Strategies may be affected.
- Serves a dashboard at `http://127.0.0.1:8000`.

The app works without paid AI credentials by using local specialist agents. If
you later want LLM-backed summaries, the agent interface in `app/agents.py` is
ready for that extension.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Configuration

Environment variables:

```bash
NEWS_REFRESH_MINUTES=60
NEWS_LOOKBACK_HOURS=72
DATABASE_PATH=./heimdall.db
HEALTHCARE_TICKERS=UNH,CVS,ELV,HUM,CI,CNC,MOH,HCA,THC,UHS,PFE,JNJ,MRK,ABBV,MDT,ISRG
```

## API

- `GET /api/dashboard` returns the current dashboard payload.
- `POST /api/refresh` triggers an immediate news pull and assessment run.
- `GET /api/articles` returns stored articles.

## Tests

```bash
python -m unittest
```
