from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.business_profile import BUSINESS_AREAS
from app.models import NewsArticle, RefreshRun, ThreatAssessment
from app.news import title_fingerprint


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


class Storage:
    def __init__(self, database_path: str, default_tickers: tuple[str, ...] = ()) -> None:
        self.database_path = database_path
        self.default_tickers = default_tickers
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    def _add_column(self, conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
        if name not in self._columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _init_db(self) -> None:
        with self.session() as conn:
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

            article_columns = {
                "canonical_url": "TEXT DEFAULT ''",
                "title_fingerprint": "TEXT DEFAULT ''",
                "reviewed": "INTEGER NOT NULL DEFAULT 0",
                "analyst_notes": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT",
                "updated_at": "TEXT",
                "first_seen_at": "TEXT",
                "last_seen_at": "TEXT",
            }
            for name, ddl in article_columns.items():
                self._add_column(conn, "articles", name, ddl)

            assessment_columns = {
                "affected_areas": "TEXT NOT NULL DEFAULT '[]'",
                "risk_categories": "TEXT NOT NULL DEFAULT '[]'",
                "confidence": "TEXT NOT NULL DEFAULT 'low'",
                "updated_at": "TEXT",
            }
            for name, ddl in assessment_columns.items():
                self._add_column(conn, "assessments", name, ddl)

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tickers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS business_areas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS refresh_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    tickers_checked INTEGER NOT NULL DEFAULT 0,
                    articles_fetched INTEGER NOT NULL DEFAULT 0,
                    new_articles_inserted INTEGER NOT NULL DEFAULT 0,
                    articles_assessed INTEGER NOT NULL DEFAULT 0,
                    errors TEXT NOT NULL DEFAULT ''
                )
                """
            )

            indexes = (
                "CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at)",
                "CREATE INDEX IF NOT EXISTS idx_articles_ticker ON articles(ticker)",
                "CREATE INDEX IF NOT EXISTS idx_articles_reviewed ON articles(reviewed)",
                "CREATE INDEX IF NOT EXISTS idx_articles_title_fingerprint ON articles(title_fingerprint)",
                "CREATE INDEX IF NOT EXISTS idx_assessments_score ON assessments(overall_score)",
                "CREATE INDEX IF NOT EXISTS idx_assessments_areas ON assessments(affected_areas)",
                "CREATE INDEX IF NOT EXISTS idx_assessments_categories ON assessments(risk_categories)",
                "CREATE INDEX IF NOT EXISTS idx_refresh_runs_started_at ON refresh_runs(started_at)",
            )
            for statement in indexes:
                conn.execute(statement)

            self._backfill_existing_rows(conn)
            self._seed_defaults(conn)

    def _backfill_existing_rows(self, conn: sqlite3.Connection) -> None:
        timestamp = _dt(_now())
        rows = conn.execute(
            "SELECT article_id, title, link, fetched_at FROM articles WHERE created_at IS NULL OR title_fingerprint = ''"
        ).fetchall()
        for row in rows:
            seen_at = row["fetched_at"] or timestamp
            conn.execute(
                """
                UPDATE articles
                SET canonical_url = COALESCE(NULLIF(canonical_url, ''), ?),
                    title_fingerprint = ?,
                    created_at = COALESCE(created_at, ?),
                    updated_at = COALESCE(updated_at, ?),
                    first_seen_at = COALESCE(first_seen_at, ?),
                    last_seen_at = COALESCE(last_seen_at, ?)
                WHERE article_id = ?
                """,
                (
                    row["link"] or "",
                    title_fingerprint(row["title"] or ""),
                    seen_at,
                    timestamp,
                    seen_at,
                    seen_at,
                    row["article_id"],
                ),
            )

        rows = conn.execute("SELECT article_id, payload FROM assessments").fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                payload = {}
            conn.execute(
                """
                UPDATE assessments
                SET affected_areas = ?,
                    risk_categories = ?,
                    confidence = ?,
                    updated_at = COALESCE(updated_at, assessed_at)
                WHERE article_id = ?
                """,
                (
                    _json(payload.get("affected_areas", [])),
                    _json(payload.get("risk_categories", [])),
                    payload.get("confidence", "low"),
                    row["article_id"],
                ),
            )

    def _seed_defaults(self, conn: sqlite3.Connection) -> None:
        timestamp = _dt(_now())
        for ticker in self.default_tickers:
            conn.execute(
                """
                INSERT INTO tickers (symbol, enabled, created_at, updated_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(symbol) DO NOTHING
                """,
                (ticker.upper(), timestamp, timestamp),
            )
        for area in BUSINESS_AREAS:
            conn.execute(
                """
                INSERT INTO business_areas (name, description, keywords, enabled, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (area.name, area.description, _json(list(area.keywords)), timestamp, timestamp),
            )

    def active_tickers(self) -> tuple[str, ...]:
        with self.session() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM tickers").fetchone()["count"]
            rows = conn.execute(
                "SELECT symbol FROM tickers WHERE enabled = 1 ORDER BY symbol"
            ).fetchall()
        if total == 0:
            return self.default_tickers
        return tuple(row["symbol"] for row in rows)

    def upsert_articles(self, articles: Iterable[NewsArticle]) -> dict[str, int]:
        processed = inserted = updated = 0
        now = _now()
        with self.session() as conn:
            for article in articles:
                processed += 1
                article_id = self._existing_article_id(conn, article) or article.article_id
                article.article_id = article_id
                exists = conn.execute(
                    "SELECT article_id FROM articles WHERE article_id = ?", (article_id,)
                ).fetchone()
                fingerprint = title_fingerprint(article.title)
                if exists:
                    conn.execute(
                        """
                        UPDATE articles
                        SET ticker = ?,
                            title = ?,
                            publisher = ?,
                            link = ?,
                            canonical_url = ?,
                            summary = ?,
                            published_at = ?,
                            fetched_at = ?,
                            title_fingerprint = ?,
                            updated_at = ?,
                            last_seen_at = ?
                        WHERE article_id = ?
                        """,
                        (
                            article.ticker or "UNKNOWN",
                            article.title,
                            article.publisher or "Unknown source",
                            article.link or "",
                            article.link or "",
                            article.summary or "",
                            _dt(article.published_at) or _dt(now),
                            _dt(article.fetched_at) or _dt(now),
                            fingerprint,
                            _dt(now),
                            _dt(now),
                            article_id,
                        ),
                    )
                    updated += 1
                else:
                    conn.execute(
                        """
                        INSERT INTO articles (
                            article_id, ticker, title, publisher, link, canonical_url,
                            summary, published_at, fetched_at, title_fingerprint,
                            reviewed, analyst_notes, created_at, updated_at,
                            first_seen_at, last_seen_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, ?, ?)
                        """,
                        (
                            article_id,
                            article.ticker or "UNKNOWN",
                            article.title,
                            article.publisher or "Unknown source",
                            article.link or "",
                            article.link or "",
                            article.summary or "",
                            _dt(article.published_at) or _dt(now),
                            _dt(article.fetched_at) or _dt(now),
                            fingerprint,
                            _dt(now),
                            _dt(now),
                            _dt(now),
                            _dt(now),
                        ),
                    )
                    inserted += 1
        return {"processed": processed, "inserted": inserted, "updated": updated}

    def _existing_article_id(self, conn: sqlite3.Connection, article: NewsArticle) -> str | None:
        if article.link:
            row = conn.execute(
                "SELECT article_id FROM articles WHERE canonical_url = ? OR link = ? LIMIT 1",
                (article.link, article.link),
            ).fetchone()
            if row:
                return row["article_id"]

        published_day = (_dt(article.published_at) or "")[:10]
        row = conn.execute(
            """
            SELECT article_id FROM articles
            WHERE ticker = ?
              AND title_fingerprint = ?
              AND substr(published_at, 1, 10) = ?
            LIMIT 1
            """,
            (article.ticker, title_fingerprint(article.title), published_day),
        ).fetchone()
        return row["article_id"] if row else None

    def save_assessments(self, assessments: Iterable[ThreatAssessment]) -> int:
        count = 0
        now = _dt(_now())
        with self.session() as conn:
            for assessment in assessments:
                article_id = self._resolve_assessment_article_id(conn, assessment.article_id)
                if not article_id:
                    continue
                payload = assessment.model_dump_json()
                conn.execute(
                    """
                    INSERT INTO assessments (
                        article_id, payload, overall_score, assessed_at,
                        affected_areas, risk_categories, confidence, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(article_id) DO UPDATE SET
                        payload = excluded.payload,
                        overall_score = excluded.overall_score,
                        assessed_at = excluded.assessed_at,
                        affected_areas = excluded.affected_areas,
                        risk_categories = excluded.risk_categories,
                        confidence = excluded.confidence,
                        updated_at = excluded.updated_at
                    """,
                    (
                        article_id,
                        payload,
                        assessment.overall_score,
                        _dt(assessment.assessed_at),
                        _json(assessment.affected_areas),
                        _json(assessment.risk_categories),
                        assessment.confidence,
                        now,
                    ),
                )
                count += 1
        return count

    def _resolve_assessment_article_id(self, conn: sqlite3.Connection, article_id: str) -> str | None:
        row = conn.execute("SELECT article_id FROM articles WHERE article_id = ?", (article_id,)).fetchone()
        return row["article_id"] if row else None

    def get_articles(self, limit: int = 100) -> list[NewsArticle]:
        rows = self.article_rows(limit=limit)
        return [self._article_model(row["article"]) for row in rows]

    def article_rows(
        self,
        *,
        limit: int = 120,
        ticker: str | None = None,
        min_score: int | None = None,
        area: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        search: str | None = None,
        reviewed: bool | None = None,
        sort: str = "highest",
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if ticker:
            clauses.append("a.ticker = ?")
            params.append(ticker.upper())
        if min_score:
            clauses.append("COALESCE(s.overall_score, 1) >= ?")
            params.append(min_score)
        if area:
            clauses.append("s.affected_areas LIKE ?")
            params.append(f"%{area}%")
        if source:
            clauses.append("a.publisher = ?")
            params.append(source)
        if date_from:
            clauses.append("date(a.published_at) >= date(?)")
            params.append(date_from)
        if date_to:
            clauses.append("date(a.published_at) <= date(?)")
            params.append(date_to)
        if reviewed is not None:
            clauses.append("a.reviewed = ?")
            params.append(1 if reviewed else 0)
        if search:
            pattern = f"%{search.lower()}%"
            clauses.append(
                """
                (
                    lower(a.title) LIKE ?
                    OR lower(a.publisher) LIKE ?
                    OR lower(a.summary) LIKE ?
                    OR lower(COALESCE(s.payload, '')) LIKE ?
                )
                """
            )
            params.extend([pattern, pattern, pattern, pattern])

        order_by = {
            "newest": "a.published_at DESC",
            "oldest": "a.published_at ASC",
            "highest": "COALESCE(s.overall_score, 1) DESC, a.published_at DESC",
            "ticker": "a.ticker ASC, a.published_at DESC",
            "publisher": "a.publisher ASC, a.published_at DESC",
        }.get(sort, "COALESCE(s.overall_score, 1) DESC, a.published_at DESC")

        sql = f"""
            SELECT
                a.*,
                s.payload,
                s.overall_score
            FROM articles a
            LEFT JOIN assessments s ON s.article_id = a.article_id
            WHERE {' AND '.join(clauses)}
            ORDER BY {order_by}
            LIMIT ?
        """
        params.append(limit)
        with self.session() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._joined_row(row) for row in rows]

    def dashboard_rows(self, limit: int = 100, **filters: Any) -> list[dict[str, Any]]:
        return self.article_rows(limit=limit, **filters)

    def article_detail(self, article_id: str) -> dict[str, Any] | None:
        rows = self.article_rows(limit=1)
        with self.session() as conn:
            row = conn.execute(
                """
                SELECT a.*, s.payload, s.overall_score
                FROM articles a
                LEFT JOIN assessments s ON s.article_id = a.article_id
                WHERE a.article_id = ?
                """,
                (article_id,),
            ).fetchone()
        return self._joined_row(row) if row else None

    def update_article(self, article_id: str, *, reviewed: bool | None, analyst_notes: str | None) -> dict[str, Any] | None:
        updates = []
        params: list[Any] = []
        if reviewed is not None:
            updates.append("reviewed = ?")
            params.append(1 if reviewed else 0)
        if analyst_notes is not None:
            updates.append("analyst_notes = ?")
            params.append(analyst_notes)
        if not updates:
            return self.article_detail(article_id)
        updates.append("updated_at = ?")
        params.append(_dt(_now()))
        params.append(article_id)
        with self.session() as conn:
            conn.execute(f"UPDATE articles SET {', '.join(updates)} WHERE article_id = ?", params)
        return self.article_detail(article_id)

    def analytics(self) -> dict[str, Any]:
        rows = self.article_rows(limit=1000, sort="newest")
        today = _now().date().isoformat()
        total = len(rows)
        scores = [row["assessment"]["overall_score"] for row in rows if row["assessment"]]
        areas = Counter()
        tickers = Counter()
        categories = Counter()
        day_counts: dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            article = row["article"]
            assessment = row["assessment"] or {}
            score = assessment.get("overall_score", 1)
            day = (article.get("published_at") or "")[:10]
            day_counts[day][score] += 1
            tickers[article["ticker"]] += 1
            for area in assessment.get("affected_areas", []):
                areas[area] += 1
            for category in assessment.get("risk_categories", []):
                categories[category] += 1

        most_area = areas.most_common(1)[0][0] if areas else "None yet"
        most_ticker = tickers.most_common(1)[0][0] if tickers else "None yet"
        return {
            "summary": {
                "total_articles": total,
                "articles_reviewed_today": sum(
                    1
                    for row in rows
                    if row["article"].get("reviewed")
                    and (row["article"].get("updated_at") or "")[:10] == today
                ),
                "high_threat_articles": sum(1 for score in scores if score >= 4),
                "average_threat_score": round(sum(scores) / len(scores), 2) if scores else 0,
                "most_affected_business_area": most_area,
                "most_active_ticker": most_ticker,
            },
            "threat_counts_by_day": [
                {
                    "day": day,
                    "total": sum(counter.values()),
                    "high": counter[4] + counter[5],
                    "scores": {str(score): counter[score] for score in range(1, 6)},
                }
                for day, counter in sorted(day_counts.items())[-14:]
            ],
            "threats_by_ticker": [
                {"ticker": ticker, "count": count} for ticker, count in tickers.most_common()
            ],
            "threats_by_area": [
                {"area": area, "count": count} for area, count in areas.most_common()
            ],
            "threats_by_risk_category": [
                {"category": category, "count": count} for category, count in categories.most_common()
            ],
        }

    def list_tickers(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM tickers ORDER BY symbol").fetchall()
        return [dict(row) for row in rows]

    def add_ticker(self, symbol: str, enabled: bool = True) -> dict[str, Any]:
        symbol = self.validate_ticker(symbol)
        timestamp = _dt(_now())
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO tickers (symbol, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (symbol, 1 if enabled else 0, timestamp, timestamp),
            )
            row = conn.execute("SELECT * FROM tickers WHERE symbol = ?", (symbol,)).fetchone()
        return dict(row)

    def update_ticker(self, ticker_id: int, symbol: str | None = None, enabled: bool | None = None) -> dict[str, Any] | None:
        updates = []
        params: list[Any] = []
        if symbol is not None:
            updates.append("symbol = ?")
            params.append(self.validate_ticker(symbol))
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if not updates:
            return self._ticker(ticker_id)
        updates.append("updated_at = ?")
        params.append(_dt(_now()))
        params.append(ticker_id)
        with self.session() as conn:
            conn.execute(f"UPDATE tickers SET {', '.join(updates)} WHERE id = ?", params)
        return self._ticker(ticker_id)

    def delete_ticker(self, ticker_id: int) -> bool:
        with self.session() as conn:
            cursor = conn.execute("DELETE FROM tickers WHERE id = ?", (ticker_id,))
        return cursor.rowcount > 0

    def _ticker(self, ticker_id: int) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute("SELECT * FROM tickers WHERE id = ?", (ticker_id,)).fetchone()
        return dict(row) if row else None

    def validate_ticker(self, symbol: str) -> str:
        clean = symbol.strip().upper()
        if not clean or len(clean) > 12 or not clean.replace(".", "").replace("-", "").isalnum():
            raise ValueError("Ticker symbols may contain letters, numbers, hyphens, or dots and must be 1-12 characters.")
        return clean

    def get_config(self, defaults: dict[str, Any]) -> dict[str, Any]:
        config = dict(defaults)
        with self.session() as conn:
            rows = conn.execute("SELECT key, value FROM config").fetchall()
        for row in rows:
            try:
                config[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                config[row["key"]] = row["value"]
        config["business_areas"] = self.list_business_areas()
        return config

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        timestamp = _dt(_now())
        with self.session() as conn:
            for key, value in updates.items():
                if value is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO config (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value), timestamp),
                )
        return self.get_config({})

    def list_business_areas(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM business_areas ORDER BY name").fetchall()
        return [
            {
                **dict(row),
                "keywords": json.loads(row["keywords"] or "[]"),
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]

    def start_refresh_run(self) -> int:
        with self.session() as conn:
            cursor = conn.execute(
                "INSERT INTO refresh_runs (started_at, status) VALUES (?, 'running')",
                (_dt(_now()),),
            )
            return int(cursor.lastrowid)

    def complete_refresh_run(
        self,
        run_id: int,
        *,
        status: str,
        tickers_checked: int,
        articles_fetched: int,
        new_articles_inserted: int,
        articles_assessed: int,
        errors: list[str] | str = "",
    ) -> None:
        error_text = "\n".join(errors) if isinstance(errors, list) else errors
        with self.session() as conn:
            conn.execute(
                """
                UPDATE refresh_runs
                SET completed_at = ?,
                    status = ?,
                    tickers_checked = ?,
                    articles_fetched = ?,
                    new_articles_inserted = ?,
                    articles_assessed = ?,
                    errors = ?
                WHERE run_id = ?
                """,
                (
                    _dt(_now()),
                    status,
                    tickers_checked,
                    articles_fetched,
                    new_articles_inserted,
                    articles_assessed,
                    error_text,
                    run_id,
                ),
            )

    def refresh_runs(self, limit: int = 20) -> list[RefreshRun]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM refresh_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            RefreshRun(
                run_id=row["run_id"],
                started_at=_parse_dt(row["started_at"]) or _now(),
                completed_at=_parse_dt(row["completed_at"]),
                status=row["status"],
                tickers_checked=row["tickers_checked"],
                articles_fetched=row["articles_fetched"],
                new_articles_inserted=row["new_articles_inserted"],
                articles_assessed=row["articles_assessed"],
                errors=row["errors"] or "",
            )
            for row in rows
        ]

    def last_successful_refresh_at(self) -> datetime | None:
        with self.session() as conn:
            row = conn.execute(
                """
                SELECT completed_at FROM refresh_runs
                WHERE status IN ('success', 'warning')
                ORDER BY completed_at DESC
                LIMIT 1
                """
            ).fetchone()
        return _parse_dt(row["completed_at"]) if row else None

    def _joined_row(self, row: sqlite3.Row) -> dict[str, Any]:
        assessment = json.loads(row["payload"]) if row["payload"] else None
        article = {
            "article_id": row["article_id"],
            "ticker": row["ticker"],
            "title": row["title"],
            "publisher": row["publisher"] or "Unknown source",
            "link": row["link"] or "",
            "summary": row["summary"] or "",
            "published_at": row["published_at"],
            "fetched_at": row["fetched_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "reviewed": bool(row["reviewed"]),
            "analyst_notes": row["analyst_notes"] or "",
        }
        return {"article": article, "assessment": assessment}

    def _article_model(self, article: dict[str, Any]) -> NewsArticle:
        return NewsArticle(
            article_id=article["article_id"],
            ticker=article["ticker"],
            title=article["title"],
            publisher=article["publisher"] or "",
            link=article["link"] or "",
            summary=article["summary"] or "",
            published_at=_parse_dt(article["published_at"]) or _now(),
            fetched_at=_parse_dt(article["fetched_at"]) or _now(),
            created_at=_parse_dt(article.get("created_at")),
            updated_at=_parse_dt(article.get("updated_at")),
            first_seen_at=_parse_dt(article.get("first_seen_at")),
            last_seen_at=_parse_dt(article.get("last_seen_at")),
            reviewed=bool(article.get("reviewed")),
            analyst_notes=article.get("analyst_notes") or "",
        )
