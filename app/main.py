from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_settings
from app.models import DashboardPayload
from app.news import NewsFetcher
from app.scheduler import NewsRefreshService
from app.storage import Storage

settings = load_settings()
storage = Storage(settings.database_path)
fetcher = NewsFetcher(settings.tickers, settings.lookback_hours)
refresh_service = NewsRefreshService(storage, fetcher, settings.refresh_minutes)


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
def dashboard() -> DashboardPayload:
    rows = storage.dashboard_rows(limit=120)
    high_threat_count = sum(
        1
        for row in rows
        if row["assessment"] and row["assessment"].get("overall_score", 1) >= 4
    )
    return DashboardPayload(
        generated_at=datetime.now(tz=UTC),
        refresh_minutes=settings.refresh_minutes,
        article_count=len(rows),
        high_threat_count=high_threat_count,
        assessments=rows,
    )


@app.post("/api/refresh")
async def refresh() -> dict[str, int | str | None]:
    return await refresh_service.refresh_now()


@app.get("/api/articles")
def articles() -> list[dict]:
    return [article.model_dump(mode="json") for article in storage.get_articles(limit=120)]


@app.get("/api/health")
def health() -> dict[str, str | None]:
    return {
        "status": "ok",
        "last_refresh_at": refresh_service.last_refresh_at.isoformat()
        if refresh_service.last_refresh_at
        else None,
        "last_error": refresh_service.last_error,
    }
