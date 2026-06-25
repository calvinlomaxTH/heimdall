from __future__ import annotations

import hashlib
import logging
import re
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


def _nested(item: dict[str, Any], *keys: str) -> Any:
    current: Any = item
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def title_fingerprint(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(words[:18])


def _published_at(item: dict[str, Any], fallback: datetime) -> datetime:
    value = (
        item.get("providerPublishTime")
        or item.get("publishTime")
        or item.get("pubDate")
        or _nested(item, "content", "pubDate")
        or _nested(item, "content", "displayTime")
    )
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


def _article_id(ticker: str, item: dict[str, Any]) -> str:
    title = item.get("title") or _nested(item, "content", "title") or ""
    link = item.get("link") or item.get("url") or _nested(item, "content", "canonicalUrl", "url")
    published = item.get("providerPublishTime") or item.get("pubDate") or _nested(item, "content", "pubDate")
    seed = item.get("uuid") or link or f"{ticker}:{title_fingerprint(str(title))}:{published}"
    return hashlib.sha256(f"{ticker}:{seed}".encode("utf-8")).hexdigest()[:24]


def normalize_article(ticker: str, item: dict[str, Any], fetched_at: datetime) -> NewsArticle | None:
    title = str(item.get("title") or _nested(item, "content", "title") or "").strip()
    if not title:
        return None
    publisher = (
        item.get("publisher")
        or item.get("provider")
        or _nested(item, "content", "provider", "displayName")
        or "Unknown source"
    )
    link = item.get("link") or item.get("url") or _nested(item, "content", "canonicalUrl", "url") or ""
    summary = (
        item.get("summary")
        or item.get("description")
        or _nested(item, "content", "summary")
        or _nested(item, "content", "description")
        or ""
    )
    return NewsArticle(
        article_id=_article_id(ticker, item),
        ticker=(ticker or "UNKNOWN").upper(),
        title=title,
        publisher=str(publisher).strip(),
        link=str(link).strip(),
        summary=str(summary).strip(),
        published_at=_published_at(item, fetched_at),
        fetched_at=fetched_at,
    )


class FetchResult(dict):
    articles: list[NewsArticle]
    errors: list[str]
    tickers_checked: int


class NewsFetcher:
    def __init__(self, tickers: tuple[str, ...], lookback_hours: int) -> None:
        self.tickers = tickers
        self.lookback_hours = lookback_hours

    def fetch(self, tickers: tuple[str, ...] | None = None) -> dict[str, Any]:
        yf = _load_yfinance()
        active_tickers = self.tickers if tickers is None else tickers
        if not active_tickers:
            return {"articles": [], "errors": [], "tickers_checked": 0}
        if yf is None:
            logger.warning("yfinance is not installed; returning demo news.")
            return {
                "articles": self._demo_news(),
                "errors": ["yfinance is not installed"],
                "tickers_checked": len(active_tickers),
            }

        fetched_at = datetime.now(tz=UTC)
        min_time = fetched_at - timedelta(hours=self.lookback_hours)
        articles: dict[str, NewsArticle] = {}
        errors: list[str] = []

        for ticker in active_tickers:
            try:
                raw_news = yf.Ticker(ticker).news or []
            except Exception as exc:
                message = f"{ticker}: {exc}"
                errors.append(message)
                logger.warning("Failed to fetch yfinance news", extra={"ticker": ticker, "error": str(exc)})
                continue

            for item in raw_news:
                article = normalize_article(ticker, item, fetched_at)
                if article and article.published_at >= min_time:
                    articles[article.article_id] = article

        if not articles:
            logger.warning("No yfinance articles found; returning demo news.")
            return {
                "articles": self._demo_news(),
                "errors": errors,
                "tickers_checked": len(active_tickers),
            }

        return {
            "articles": sorted(articles.values(), key=lambda article: article.published_at, reverse=True),
            "errors": errors,
            "tickers_checked": len(active_tickers),
        }

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
