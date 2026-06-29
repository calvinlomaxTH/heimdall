from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.agents import assess_articles
from app.news import NewsFetcher
from app.storage import Storage

logger = logging.getLogger(__name__)


class NewsRefreshService:
    def __init__(
        self,
        storage: Storage,
        fetcher: NewsFetcher,
        refresh_minutes: int,
    ) -> None:
        self.storage = storage
        self.fetcher = fetcher
        self.refresh_minutes = refresh_minutes
        self.last_refresh_at: datetime | None = None
        self.last_error: str | None = None
        self.next_refresh_at: datetime | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def refresh_now(self) -> dict[str, int | str | None]:
        async with self._lock:
            run_id = await asyncio.to_thread(self.storage.start_refresh_run)
            try:
                tickers = await asyncio.to_thread(self.storage.active_tickers)
                newsapi_provider, newsapi_query = self.fetcher.newsapi_cache_key()
                cached_newsapi = await asyncio.to_thread(
                    self.storage.get_newsapi_cache,
                    newsapi_provider,
                    newsapi_query,
                )
                fetch_result = await asyncio.to_thread(
                    self.fetcher.fetch,
                    tickers,
                    cached_newsapi["payload"] if cached_newsapi else None,
                )
                if fetch_result.get("newsapi_payload") and cached_newsapi is None:
                    await asyncio.to_thread(
                        self.storage.save_newsapi_cache,
                        newsapi_provider,
                        newsapi_query,
                        fetch_result["newsapi_payload"],
                    )
                articles = fetch_result["articles"]
                upsert_result = await asyncio.to_thread(self.storage.upsert_articles, articles)
                assessments = assess_articles(articles)
                assessment_count = await asyncio.to_thread(self.storage.save_assessments, assessments)
                self.last_refresh_at = datetime.now(tz=UTC)
                self.next_refresh_at = self.last_refresh_at + timedelta(minutes=self.refresh_minutes)
                self.last_error = None
                errors = fetch_result.get("errors", [])
                status = "warning" if errors else "success"
                await asyncio.to_thread(
                    self.storage.complete_refresh_run,
                    run_id,
                    status=status,
                    tickers_checked=fetch_result.get("tickers_checked", len(tickers)),
                    articles_fetched=len(articles),
                    new_articles_inserted=upsert_result["inserted"],
                    articles_assessed=assessment_count,
                    errors=errors,
                )
                return {
                    "run_id": run_id,
                    "articles": len(articles),
                    "new_articles_inserted": upsert_result["inserted"],
                    "assessments": assessment_count,
                    "last_refresh_at": self.last_refresh_at.isoformat(),
                    "next_refresh_at": self.next_refresh_at.isoformat(),
                    "error": None,
                }
            except Exception as exc:
                logger.exception("News refresh failed")
                self.last_error = str(exc)
                await asyncio.to_thread(
                    self.storage.complete_refresh_run,
                    run_id,
                    status="failed",
                    tickers_checked=0,
                    articles_fetched=0,
                    new_articles_inserted=0,
                    articles_assessed=0,
                    errors=str(exc),
                )
                return {
                    "run_id": run_id,
                    "articles": 0,
                    "new_articles_inserted": 0,
                    "assessments": 0,
                    "last_refresh_at": self.last_refresh_at.isoformat() if self.last_refresh_at else None,
                    "next_refresh_at": self.next_refresh_at.isoformat() if self.next_refresh_at else None,
                    "error": self.last_error,
                }

    async def _loop(self) -> None:
        await self.refresh_now()
        while True:
            self.next_refresh_at = datetime.now(tz=UTC) + timedelta(minutes=self.refresh_minutes)
            await asyncio.sleep(self.refresh_minutes * 60)
            await self.refresh_now()
