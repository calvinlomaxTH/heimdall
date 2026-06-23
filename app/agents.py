from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from app.business_profile import BUSINESS_AREAS, COMPANY_NAME
from app.models import AgentFinding, NewsArticle, ThreatAssessment


HIGH_SIGNAL_TERMS = {
    "lawsuit",
    "investigation",
    "fraud",
    "breach",
    "cyber",
    "bankruptcy",
    "recall",
    "probe",
    "sanction",
    "penalty",
    "rate cut",
    "cuts",
    "crackdown",
    "federal",
    "cms",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9-]+", text.lower())


def _score_from_hits(base: int, hits: int, high_signal_hits: int = 0) -> int:
    return min(5, max(1, base + min(2, hits // 2) + min(2, high_signal_hits)))


def _affected_areas(text: str) -> list[str]:
    lowered = text.lower()
    matched = []
    for area in BUSINESS_AREAS:
        if any(keyword in lowered for keyword in area.keywords):
            matched.append(area.name)
    if matched:
        return matched
    return ["Market intelligence and growth"]


@dataclass(frozen=True)
class ThreatAgent:
    name: str
    focus: str
    keywords: tuple[str, ...]
    base_score: int = 1

    def assess(self, article: NewsArticle) -> AgentFinding:
        text = f"{article.title} {article.summary}"
        lowered = text.lower()
        hits = [keyword for keyword in self.keywords if keyword in lowered]
        high_hits = [term for term in HIGH_SIGNAL_TERMS if term in lowered]
        score = _score_from_hits(self.base_score, len(hits), len(high_hits))

        if hits:
            rationale = f"{self.focus} signals appear in the headline or summary."
        else:
            rationale = f"No strong {self.focus.lower()} signal detected."

        return AgentFinding(
            agent=self.name,
            score=score,
            rationale=rationale,
            signals=sorted(set(hits + high_hits)),
            affected_areas=_affected_areas(text),
        )


AGENTS = (
    ThreatAgent(
        name="Policy Radar Agent",
        focus="Policy and reimbursement",
        keywords=(
            "cms",
            "hhs",
            "medicare",
            "medicaid",
            "reimbursement",
            "rule",
            "regulation",
            "regulatory",
            "prior authorization",
            "rate",
            "aca",
        ),
    ),
    ThreatAgent(
        name="Payer-Provider Market Agent",
        focus="Payer, provider, and contracting",
        keywords=(
            "payer",
            "provider",
            "hospital",
            "health system",
            "insurer",
            "insurance",
            "network",
            "contract",
            "utilization",
            "margin",
            "premium",
        ),
    ),
    ThreatAgent(
        name="Transformation Demand Agent",
        focus="Care model and value-based transformation",
        keywords=(
            "value-based",
            "risk",
            "quality",
            "outcomes",
            "population health",
            "primary care",
            "behavioral health",
            "care management",
            "affordability",
        ),
    ),
    ThreatAgent(
        name="Commercial Intelligence Agent",
        focus="Competitive and financial",
        keywords=(
            "earnings",
            "revenue",
            "profit",
            "margin",
            "acquisition",
            "merger",
            "partnership",
            "guidance",
            "market share",
            "growth",
        ),
    ),
    ThreatAgent(
        name="Reputation Risk Agent",
        focus="Reputation, legal, and operational resilience",
        keywords=(
            "lawsuit",
            "investigation",
            "probe",
            "fraud",
            "breach",
            "cyber",
            "outage",
            "strike",
            "recall",
            "patient safety",
            "controversy",
        ),
    ),
)


def _severity(score: int) -> str:
    return {
        1: "Low",
        2: "Guarded",
        3: "Moderate",
        4: "High",
        5: "Critical",
    }[score]


def _recommended_action(score: int, areas: list[str]) -> str:
    lead_area = areas[0] if areas else "market intelligence"
    if score >= 5:
        return f"Escalate immediately: brief leadership on {lead_area} exposure and prepare client-facing guidance."
    if score == 4:
        return f"Monitor daily and prepare a rapid advisory note for clients tied to {lead_area}."
    if score == 3:
        return f"Track follow-up coverage and add implications for {lead_area} to the next client intelligence update."
    if score == 2:
        return "Keep on watchlist; no immediate client action required unless more sources confirm the signal."
    return "Archive for context; revisit only if the story develops."


def assess_article(article: NewsArticle) -> ThreatAssessment:
    findings = [agent.assess(article) for agent in AGENTS]
    scores = [finding.score for finding in findings]
    score_counts = Counter(scores)
    weighted = round((max(scores) * 0.55) + (sum(scores) / len(scores) * 0.45))
    overall_score = min(5, max(1, weighted))

    all_areas = []
    for finding in sorted(findings, key=lambda item: item.score, reverse=True):
        for area in finding.affected_areas:
            if area not in all_areas:
                all_areas.append(area)

    top_agent = max(findings, key=lambda item: item.score)
    impact_summary = (
        f"{COMPANY_NAME} exposure is concentrated in {', '.join(all_areas[:3])}. "
        f"The strongest signal came from {top_agent.agent.lower()} with a "
        f"{_severity(top_agent.score).lower()} reading."
    )
    if score_counts[5] >= 2 or (overall_score >= 4 and len(all_areas) >= 3):
        overall_score = min(5, overall_score + 1)

    return ThreatAssessment(
        article_id=article.article_id,
        overall_score=overall_score,
        severity_label=_severity(overall_score),
        affected_areas=all_areas,
        impact_summary=impact_summary,
        recommended_action=_recommended_action(overall_score, all_areas),
        agent_findings=findings,
        assessed_at=datetime.now(tz=UTC),
    )


def assess_articles(articles: list[NewsArticle]) -> list[ThreatAssessment]:
    return [assess_article(article) for article in articles]
