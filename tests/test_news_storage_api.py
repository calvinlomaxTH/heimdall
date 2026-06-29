from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from datetime import UTC, datetime

import app.news as news_module
from app.agents import assess_article, detect_risk_categories
from app.config import DEFAULT_TICKERS
from app.models import NewsArticle
from app.news import NewsFetcher, normalize_article, normalize_newsapi_article
from app.storage import Storage


def article(article_id: str = "a1", link: str = "https://example.test/a") -> NewsArticle:
    now = datetime.now(tz=UTC)
    return NewsArticle(
        article_id=article_id,
        ticker="UNH",
        title="CMS investigates Medicare Advantage prior authorization breach",
        publisher="Test Source",
        link=link,
        summary="Federal policy and cybersecurity risk may pressure payers.",
        published_at=now,
        fetched_at=now,
    )


class NewsNormalizationTests(unittest.TestCase):
    def test_normalize_article_handles_nested_yahoo_shape(self) -> None:
        fetched_at = datetime.now(tz=UTC)
        normalized = normalize_article(
            "unh",
            {
                "content": {
                    "title": "CMS updates Medicare Advantage policy",
                    "provider": {"displayName": "Yahoo Finance"},
                    "canonicalUrl": {"url": "https://finance.yahoo.test/story"},
                    "summary": "A policy update affects payer operations.",
                    "pubDate": "2026-06-25T10:00:00Z",
                }
            },
            fetched_at,
        )

        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized.ticker, "UNH")
        self.assertEqual(normalized.publisher, "Yahoo Finance")
        self.assertEqual(normalized.link, "https://finance.yahoo.test/story")

    def test_normalize_newsapi_org_article(self) -> None:
        fetched_at = datetime.now(tz=UTC)
        normalized = normalize_newsapi_article(
            {
                "source": {"name": "Healthcare Dive"},
                "title": "UnitedHealth faces Medicare Advantage oversight",
                "description": "CMS policy scrutiny affects payer strategy.",
                "url": "https://example.test/newsapi",
                "publishedAt": "2026-06-25T12:00:00Z",
            },
            fetched_at,
            ("UNH", "CVS"),
            "newsapi_org",
        )

        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized.ticker, "UNH")
        self.assertEqual(normalized.publisher, "Healthcare Dive")
        self.assertEqual(normalized.link, "https://example.test/newsapi")

    def test_cached_newsapi_payload_can_be_reused_without_key(self) -> None:
        original_loader = news_module._load_yfinance
        news_module._load_yfinance = lambda: None
        fetcher = NewsFetcher(
            ("UNH",),
            72,
            newsapi_key="",
            newsapi_provider="newsapi_org",
            newsapi_query="healthcare",
        )
        try:
            result = fetcher.fetch(
                ("UNH",),
                {
                    "articles": [
                        {
                            "source": {"name": "Cached Source"},
                            "title": "Optum expands healthcare analytics program",
                            "description": "Growth in payer analytics.",
                            "url": "https://example.test/cached",
                            "publishedAt": datetime.now(tz=UTC).isoformat(),
                        }
                    ]
                },
            )
        finally:
            news_module._load_yfinance = original_loader

        self.assertTrue(any(item.ticker == "UNH" for item in result["articles"]))
        self.assertIsNone(result.get("newsapi_payload"))


class ThreatDetectionTests(unittest.TestCase):
    def test_risk_categories_and_assessment_fields(self) -> None:
        categories = detect_risk_categories(
            "CMS reimbursement lawsuit and cybersecurity breach creates payer pressure"
        )
        self.assertIn("regulatory", categories)
        self.assertIn("reimbursement", categories)
        self.assertIn("litigation", categories)
        self.assertIn("cybersecurity", categories)
        self.assertIn("payer pressure", categories)

        assessment = assess_article(article())
        self.assertGreaterEqual(assessment.overall_score, 4)
        self.assertIn("regulatory", assessment.risk_categories)
        self.assertIn("Policy and regulatory advisory", assessment.affected_areas)
        self.assertIn(assessment.confidence, {"medium", "high"})


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(os.path.join(self.tmp.name, "test.db"), DEFAULT_TICKERS[:2])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_migration_seeds_tickers_and_business_areas(self) -> None:
        self.assertEqual(set(self.storage.active_tickers()), set(DEFAULT_TICKERS[:2]))
        self.assertTrue(self.storage.list_business_areas())

    def test_upsert_deduplicates_by_url(self) -> None:
        first = self.storage.upsert_articles([article("one")])
        second = self.storage.upsert_articles([article("two")])

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(len(self.storage.article_rows()), 1)

    def test_refresh_run_tracking(self) -> None:
        run_id = self.storage.start_refresh_run()
        self.storage.complete_refresh_run(
            run_id,
            status="success",
            tickers_checked=2,
            articles_fetched=3,
            new_articles_inserted=1,
            articles_assessed=3,
            errors=[],
        )
        runs = self.storage.refresh_runs()

        self.assertEqual(runs[0].run_id, run_id)
        self.assertEqual(runs[0].new_articles_inserted, 1)

    def test_newsapi_cache_round_trip(self) -> None:
        payload = {"articles": [{"title": "Cached healthcare story"}]}
        self.storage.save_newsapi_cache("newsapi_org", "healthcare", payload)
        cached = self.storage.get_newsapi_cache("newsapi_org", "healthcare")

        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached["payload"], payload)

    def test_ticker_configuration(self) -> None:
        created = self.storage.add_ticker("hca", True)
        updated = self.storage.update_ticker(created["id"], enabled=False)

        self.assertEqual(created["symbol"], "HCA")
        self.assertFalse(bool(updated["enabled"]))

    def test_disabling_all_tickers_does_not_fall_back_to_defaults(self) -> None:
        for row in self.storage.list_tickers():
            self.storage.update_ticker(row["id"], enabled=False)

        self.assertEqual(self.storage.active_tickers(), ())


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(cls.tmp.name, "api.db")
        os.environ["HEALTHCARE_TICKERS"] = "UNH,HCA"
        import app.main as main

        cls.main = importlib.reload(main)
        from fastapi.testclient import TestClient

        cls.client = TestClient(cls.main.app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_api_endpoints(self) -> None:
        ticker_response = self.client.post("/api/tickers", json={"symbol": "PFE", "enabled": True})
        self.assertEqual(ticker_response.status_code, 200)

        config_response = self.client.patch("/api/config", json={"refresh_minutes": 30})
        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(config_response.json()["refresh_minutes"], 30)

        dashboard_response = self.client.get("/api/dashboard")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("assessments", dashboard_response.json())

        analytics_response = self.client.get("/api/analytics")
        self.assertEqual(analytics_response.status_code, 200)
        self.assertIn("summary", analytics_response.json())

        runs_response = self.client.get("/api/refresh-runs")
        self.assertEqual(runs_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
