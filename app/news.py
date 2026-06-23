from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import NewsArticle

logger = logging.getLogger(__name__)


def _load_yfinance():
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return None
    return yf


def _published_at(item: dict[str, Any]) -> datetime:
    value = item.get("providerPublishTime") or item.get("publishTime") or item.get("pubDate")
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=UTC)


def _article_id(ticker: str, item: dict[str, Any]) -> str:
    seed = item.get("uuid") or item.get("link") or item.get("title") or repr(item)
    return hashlib.sha256(f"{ticker}:{seed}".encode("utf-8")).hexdigest()[:24]


def _normalize(ticker: str, item: dict[str, Any], fetched_at: datetime) -> NewsArticle | None:
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    return NewsArticle(
        article_id=_article_id(ticker, item),
        ticker=ticker,
        title=title,
        publisher=str(item.get("publisher") or item.get("provider") or "").strip(),
        link=str(item.get("link") or item.get("url") or "").strip(),
        summary=str(item.get("summary") or item.get("description") or "").strip(),
        published_at=_published_at(item),
        fetched_at=fetched_at,
    )


class NewsFetcher:
    def __init__(self, tickers: tuple[str, ...], lookback_hours: int) -> None:
        self.tickers = tickers
        self.lookback_hours = lookback_hours

    def fetch(self) -> list[NewsArticle]:
        yf = _load_yfinance()
        if yf is None:
            logger.warning("yfinance is not installed; returning demo news.")
            return self._demo_news()

        fetched_at = datetime.now(tz=UTC)
        min_time = fetched_at - timedelta(hours=self.lookback_hours)
        articles: dict[str, NewsArticle] = {}

        for ticker in self.tickers:
            try:
                raw_news = yf.Ticker(ticker).news or []
            except Exception as exc:
                logger.warning("Failed to fetch yfinance news for %s: %s", ticker, exc)
                continue

            for item in raw_news:
                article = _normalize(ticker, item, fetched_at)
                if article and article.published_at >= min_time:
                    articles[article.article_id] = article

        if not articles:
            logger.warning("No yfinance articles found; returning demo news.")
            return self._demo_news()

        return sorted(articles.values(), key=lambda article: article.published_at, reverse=True)

    def _demo_news(self) -> list[NewsArticle]:
        fetched_at = datetime.now(tz=UTC)
        samples = (
            (
                "UNH",
                "CMS proposes new Medicare Advantage prior authorization oversight rules",
                "Demo Wire",
                "Regulatory pressure could reshape payer operations and client strategy needs.",
            ),
            (
                "HCA",
                "Hospital operators warn labor costs and reimbursement rates will pressure margins",
                "Demo Wire",
                "Provider margin stress may affect transformation and growth advisory demand.",
            ),
            (
                "PFE",
                "Drug pricing debate intensifies as lawmakers examine pharmaceutical rebates",
                "Demo Wire",
                "Policy shifts could affect market intelligence and regulatory advisory work.",
            ),
        )
        return [
            NewsArticle(
                article_id=hashlib.sha256(f"demo:{title}".encode("utf-8")).hexdigest()[:24],
                ticker=ticker,
                title=title,
                publisher=publisher,
                link="",
                summary=summary,
                published_at=fetched_at - timedelta(minutes=index * 17),
                fetched_at=fetched_at,
            )
            for index, (ticker, title, publisher, summary) in enumerate(samples)
        ]
