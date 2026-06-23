from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

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
            try:
                articles = await asyncio.to_thread(self.fetcher.fetch)
                assessments = assess_articles(articles)
                article_count = await asyncio.to_thread(self.storage.upsert_articles, articles)
                assessment_count = await asyncio.to_thread(self.storage.save_assessments, assessments)
                self.last_refresh_at = datetime.now(tz=UTC)
                self.last_error = None
                return {
                    "articles": article_count,
                    "assessments": assessment_count,
                    "last_refresh_at": self.last_refresh_at.isoformat(),
                    "error": None,
                }
            except Exception as exc:
                logger.exception("News refresh failed")
                self.last_error = str(exc)
                return {
                    "articles": 0,
                    "assessments": 0,
                    "last_refresh_at": self.last_refresh_at.isoformat() if self.last_refresh_at else None,
                    "error": self.last_error,
                }

    async def _loop(self) -> None:
        await self.refresh_now()
        while True:
            await asyncio.sleep(self.refresh_minutes * 60)
            await self.refresh_now()
