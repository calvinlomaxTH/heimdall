from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from app.models import NewsArticle, ThreatAssessment


def _dt(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class Storage:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    article_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    title TEXT NOT NULL,
                    publisher TEXT,
                    link TEXT,
                    summary TEXT,
                    published_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assessments (
                    article_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    overall_score INTEGER NOT NULL,
                    assessed_at TEXT NOT NULL,
                    FOREIGN KEY(article_id) REFERENCES articles(article_id)
                )
                """
            )

    def upsert_articles(self, articles: Iterable[NewsArticle]) -> int:
        count = 0
        with self.connect() as conn:
            for article in articles:
                conn.execute(
                    """
                    INSERT INTO articles (
                        article_id, ticker, title, publisher, link, summary,
                        published_at, fetched_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(article_id) DO UPDATE SET
                        ticker = excluded.ticker,
                        title = excluded.title,
                        publisher = excluded.publisher,
                        link = excluded.link,
                        summary = excluded.summary,
                        published_at = excluded.published_at,
                        fetched_at = excluded.fetched_at
                    """,
                    (
                        article.article_id,
                        article.ticker,
                        article.title,
                        article.publisher,
                        article.link,
                        article.summary,
                        _dt(article.published_at),
                        _dt(article.fetched_at),
                    ),
                )
                count += 1
        return count

    def get_articles(self, limit: int = 100) -> list[NewsArticle]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM articles
                ORDER BY published_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            NewsArticle(
                article_id=row["article_id"],
                ticker=row["ticker"],
                title=row["title"],
                publisher=row["publisher"] or "",
                link=row["link"] or "",
                summary=row["summary"] or "",
                published_at=datetime.fromisoformat(row["published_at"]),
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
            )
            for row in rows
        ]

    def save_assessments(self, assessments: Iterable[ThreatAssessment]) -> int:
        count = 0
        with self.connect() as conn:
            for assessment in assessments:
                conn.execute(
                    """
                    INSERT INTO assessments (
                        article_id, payload, overall_score, assessed_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(article_id) DO UPDATE SET
                        payload = excluded.payload,
                        overall_score = excluded.overall_score,
                        assessed_at = excluded.assessed_at
                    """,
                    (
                        assessment.article_id,
                        assessment.model_dump_json(),
                        assessment.overall_score,
                        _dt(assessment.assessed_at),
                    ),
                )
                count += 1
        return count

    def dashboard_rows(self, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.article_id,
                    a.ticker,
                    a.title,
                    a.publisher,
                    a.link,
                    a.summary,
                    a.published_at,
                    s.payload,
                    s.overall_score
                FROM articles a
                LEFT JOIN assessments s ON s.article_id = a.article_id
                ORDER BY COALESCE(s.overall_score, 1) DESC, a.published_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        payload = []
        for row in rows:
            assessment = json.loads(row["payload"]) if row["payload"] else None
            payload.append(
                {
                    "article": {
                        "article_id": row["article_id"],
                        "ticker": row["ticker"],
                        "title": row["title"],
                        "publisher": row["publisher"],
                        "link": row["link"],
                        "summary": row["summary"],
                        "published_at": row["published_at"],
                    },
                    "assessment": assessment,
                }
            )
        return payload
