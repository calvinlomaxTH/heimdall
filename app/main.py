from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_settings
from app.models import (
    AnalyticsPayload,
    ArticlePatch,
    ConfigPatch,
    DashboardPayload,
    TickerPatch,
    TickerPayload,
)
from app.news import NewsFetcher
from app.scheduler import NewsRefreshService
from app.storage import Storage

settings = load_settings()
storage = Storage(settings.database_path, settings.tickers)
stored_config = storage.get_config(
    {"refresh_minutes": settings.refresh_minutes, "lookback_hours": settings.lookback_hours}
)
fetcher = NewsFetcher(settings.tickers, int(stored_config.get("lookback_hours", settings.lookback_hours)))
refresh_service = NewsRefreshService(
    storage,
    fetcher,
    int(stored_config.get("refresh_minutes", settings.refresh_minutes)),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await refresh_service.start()
    yield
    await refresh_service.stop()


app = FastAPI(title="Heimdall Healthcare Threat Dashboard", lifespan=lifespan)

static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/dashboard", response_model=DashboardPayload)
def dashboard(
    ticker: str | None = None,
    min_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    area: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    reviewed: bool | None = None,
    sort: str = "highest",
) -> DashboardPayload:
    rows = storage.dashboard_rows(
        limit=240,
        ticker=ticker,
        min_score=min_score,
        area=area,
        source=source,
        date_from=date_from,
        date_to=date_to,
        search=search,
        reviewed=reviewed,
        sort=sort,
    )
    high_threat_count = sum(
        1
        for row in rows
        if row["assessment"] and row["assessment"].get("overall_score", 1) >= 4
    )
    last_success = storage.last_successful_refresh_at()
    return DashboardPayload(
        generated_at=datetime.now(tz=UTC),
        refresh_minutes=refresh_service.refresh_minutes,
        next_refresh_at=refresh_service.next_refresh_at,
        last_successful_refresh_at=last_success,
        article_count=len(rows),
        high_threat_count=high_threat_count,
        assessments=rows,
        high_priority=[
            row
            for row in rows
            if row["assessment"] and row["assessment"].get("overall_score", 1) >= 4
        ][:8],
        recently_added=sorted(
            rows,
            key=lambda row: row["article"].get("created_at") or row["article"].get("published_at") or "",
            reverse=True,
        )[:8],
    )


@app.post("/api/refresh")
async def refresh() -> dict[str, int | str | None]:
    return await refresh_service.refresh_now()


@app.get("/api/articles")
def articles(
    ticker: str | None = None,
    min_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    area: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    reviewed: bool | None = None,
    sort: str = "newest",
) -> list[dict[str, Any]]:
    return storage.article_rows(
        limit=240,
        ticker=ticker,
        min_score=min_score,
        area=area,
        source=source,
        date_from=date_from,
        date_to=date_to,
        search=search,
        reviewed=reviewed,
        sort=sort,
    )


@app.get("/api/articles/{article_id}")
def article_detail(article_id: str) -> dict[str, Any]:
    article = storage.article_detail(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@app.patch("/api/articles/{article_id}")
def update_article(article_id: str, patch: ArticlePatch) -> dict[str, Any]:
    article = storage.update_article(
        article_id,
        reviewed=patch.reviewed,
        analyst_notes=patch.analyst_notes,
    )
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@app.get("/api/refresh-runs")
def refresh_runs() -> list[dict[str, Any]]:
    return [run.model_dump(mode="json") for run in storage.refresh_runs(limit=25)]


@app.get("/api/analytics", response_model=AnalyticsPayload)
def analytics() -> AnalyticsPayload:
    payload = storage.analytics()
    return AnalyticsPayload(generated_at=datetime.now(tz=UTC), **payload)


@app.get("/api/tickers")
def tickers() -> list[dict[str, Any]]:
    return storage.list_tickers()


@app.post("/api/tickers")
def add_ticker(payload: TickerPayload) -> dict[str, Any]:
    try:
        return storage.add_ticker(payload.symbol, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/tickers/{ticker_id}")
def update_ticker(ticker_id: int, payload: TickerPatch) -> dict[str, Any]:
    try:
        ticker = storage.update_ticker(ticker_id, payload.symbol, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return ticker


@app.delete("/api/tickers/{ticker_id}")
def delete_ticker(ticker_id: int) -> dict[str, bool]:
    deleted = storage.delete_ticker(ticker_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return {"deleted": True}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return storage.get_config(
        {
            "refresh_minutes": refresh_service.refresh_minutes,
            "lookback_hours": fetcher.lookback_hours,
        }
    )


@app.patch("/api/config")
def update_config(payload: ConfigPatch) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    config = storage.update_config(updates)
    if payload.refresh_minutes is not None:
        refresh_service.refresh_minutes = payload.refresh_minutes
    if payload.lookback_hours is not None:
        fetcher.lookback_hours = payload.lookback_hours
    return storage.get_config(
        {
            "refresh_minutes": refresh_service.refresh_minutes,
            "lookback_hours": fetcher.lookback_hours,
        }
    )


@app.get("/api/health")
def health() -> dict[str, str | None]:
    return {
        "status": "ok",
        "last_refresh_at": refresh_service.last_refresh_at.isoformat()
        if refresh_service.last_refresh_at
        else None,
        "last_error": refresh_service.last_error,
        "next_refresh_at": refresh_service.next_refresh_at.isoformat()
        if refresh_service.next_refresh_at
        else None,
    }
