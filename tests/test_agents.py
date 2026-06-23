from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.agents import assess_article
from app.models import NewsArticle


class ThreatAssessmentTests(unittest.TestCase):
    def article(self, title: str, summary: str = "") -> NewsArticle:
        now = datetime.now(tz=UTC)
        return NewsArticle(
            article_id="test",
            ticker="UNH",
            title=title,
            publisher="Test",
            link="",
            summary=summary,
            published_at=now,
            fetched_at=now,
        )

    def test_regulatory_and_payer_story_scores_high(self) -> None:
        assessment = assess_article(
            self.article(
                "CMS investigation targets Medicare Advantage prior authorization rules",
                "Federal regulators probe insurer utilization and reimbursement practices.",
            )
        )

        self.assertGreaterEqual(assessment.overall_score, 4)
        self.assertIn("Policy and regulatory advisory", assessment.affected_areas)
        self.assertIn("Payer and provider strategy", assessment.affected_areas)

    def test_generic_growth_story_scores_lower(self) -> None:
        assessment = assess_article(
            self.article(
                "Healthcare company announces regional market growth",
                "The company opened a new office and expanded hiring.",
            )
        )

        self.assertLessEqual(assessment.overall_score, 3)
        self.assertIn("Market intelligence and growth", assessment.affected_areas)


if __name__ == "__main__":
    unittest.main()
