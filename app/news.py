from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import NewsArticle

logger = logging.getLogger(__name__)

NEWSAPI_ORG_ENDPOINT = "https://newsapi.org/v2/everything"
NEWSAPI_AI_ENDPOINT = "https://eventregistry.org/api/v1/article/getArticles"


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
        or item.get("publishedAt")
        or item.get("dateTimePub")
        or item.get("dateTime")
        or item.get("date")
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


def _detect_ticker(text: str, tickers: tuple[str, ...]) -> str:
    lowered = text.lower()
    company_aliases = {
        "UNH": ("unitedhealth", "unitedhealthcare", "optum"),
        "CVS": ("cvs", "caremark", "aetna"),
        "ELV": ("elevance", "anthem"),
        "HUM": ("humana",),
        "CI": ("cigna", "evernorth"),
        "CNC": ("centene",),
        "MOH": ("molina",),
        "HCA": ("hca",),
        "THC": ("tenet",),
        "UHS": ("universal health services",),
        "PFE": ("pfizer",),
        "JNJ": ("johnson & johnson", "johnson and johnson", "janssen"),
        "MRK": ("merck",),
        "ABBV": ("abbvie",),
        "MDT": ("medtronic",),
        "ISRG": ("intuitive surgical",),
    }
    for ticker in tickers:
        symbol = ticker.upper()
        if re.search(rf"\b{re.escape(symbol.lower())}\b", lowered):
            return symbol
        if any(alias in lowered for alias in company_aliases.get(symbol, ())):
            return symbol
    return "NEWSAPI"


def normalize_newsapi_article(
    item: dict[str, Any],
    fetched_at: datetime,
    tickers: tuple[str, ...],
    provider: str,
) -> NewsArticle | None:
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    publisher = (
        source.get("name")
        or source.get("title")
        or item.get("sourceName")
        or item.get("sourceTitle")
        or "NewsAPI"
    )
    link = item.get("url") or item.get("uri") or ""
    summary = item.get("description") or item.get("body") or item.get("content") or ""
    ticker = _detect_ticker(f"{title} {summary}", tickers)
    seed = link or f"{provider}:{title_fingerprint(title)}:{item.get('publishedAt') or item.get('dateTimePub')}"
    article_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return NewsArticle(
        article_id=article_id,
        ticker=ticker,
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
    def __init__(
        self,
        tickers: tuple[str, ...],
        lookback_hours: int,
        newsapi_key: str = "",
        newsapi_provider: str = "auto",
        newsapi_query: str = "healthcare",
    ) -> None:
        self.tickers = tickers
        self.lookback_hours = lookback_hours
        self.newsapi_key = newsapi_key
        self.newsapi_provider = newsapi_provider
        self.newsapi_query = newsapi_query

    def newsapi_cache_key(self) -> tuple[str, str]:
        return self._resolved_newsapi_provider(), self.newsapi_query

    def _resolved_newsapi_provider(self) -> str:
        if self.newsapi_provider != "auto":
            return self.newsapi_provider
        return "newsapi_ai" if "-" in self.newsapi_key else "newsapi_org"

    def fetch(
        self,
        tickers: tuple[str, ...] | None = None,
        newsapi_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        yf = _load_yfinance()
        active_tickers = self.tickers if tickers is None else tickers
        if not active_tickers:
            return {"articles": [], "errors": [], "tickers_checked": 0}
        fetched_at = datetime.now(tz=UTC)
        min_time = fetched_at - timedelta(hours=self.lookback_hours)
        articles: dict[str, NewsArticle] = {}
        errors: list[str] = []

        if yf is None:
            logger.warning("yfinance is not installed.")
            errors.append("yfinance is not installed")
        else:
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

        newsapi_payload_to_cache = None
        provider = self._resolved_newsapi_provider()
        if newsapi_payload:
            newsapi_articles = self._articles_from_newsapi_payload(newsapi_payload, fetched_at, active_tickers, provider)
            for article in newsapi_articles:
                if article and article.published_at >= min_time:
                    articles[article.article_id] = article
        elif self.newsapi_key:
            try:
                pulled_payload = self._fetch_newsapi_payload(provider)
                newsapi_payload_to_cache = pulled_payload
                newsapi_articles = self._articles_from_newsapi_payload(
                    pulled_payload,
                    fetched_at,
                    active_tickers,
                    provider,
                )
                for article in newsapi_articles:
                    if article and article.published_at >= min_time:
                        articles[article.article_id] = article
            except Exception as exc:
                errors.append(f"NewsAPI: {exc}")
                logger.warning("Failed to fetch NewsAPI data", extra={"provider": provider, "error": str(exc)})

        if not articles:
            logger.warning("No yfinance articles found; returning demo news.")
            return {
                "articles": self._demo_news(),
                "errors": errors,
                "tickers_checked": len(active_tickers),
                "newsapi_payload": newsapi_payload_to_cache,
            }

        return {
            "articles": sorted(articles.values(), key=lambda article: article.published_at, reverse=True),
            "errors": errors,
            "tickers_checked": len(active_tickers),
            "newsapi_payload": newsapi_payload_to_cache,
        }

    def _fetch_newsapi_payload(self, provider: str) -> dict[str, Any]:
        if provider == "newsapi_ai":
            body = {
                "action": "getArticles",
                "keyword": self.newsapi_query,
                "lang": "eng",
                "articlesPage": 1,
                "articlesCount": 100,
                "articlesSortBy": "date",
                "articlesSortByAsc": False,
                "dataType": ["news"],
                "resultType": "articles",
                "apiKey": self.newsapi_key,
            }
            request = urllib.request.Request(
                NEWSAPI_AI_ENDPOINT,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
        else:
            params = urllib.parse.urlencode(
                {
                    "q": self.newsapi_query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 100,
                    "apiKey": self.newsapi_key,
                }
            )
            request = urllib.request.Request(f"{NEWSAPI_ORG_ENDPOINT}?{params}")

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"{provider} returned HTTP {exc.code}: {detail}") from exc

    def _articles_from_newsapi_payload(
        self,
        payload: dict[str, Any],
        fetched_at: datetime,
        tickers: tuple[str, ...],
        provider: str,
    ) -> list[NewsArticle]:
        if provider == "newsapi_ai":
            raw_articles = _nested(payload, "articles", "results") or []
        else:
            raw_articles = payload.get("articles") or []
        articles = [
            normalize_newsapi_article(item, fetched_at, tickers, provider)
            for item in raw_articles
            if isinstance(item, dict)
        ]
        return [article for article in articles if article is not None]

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
