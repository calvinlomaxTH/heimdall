from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    article_id: str
    ticker: str
    title: str
    publisher: str = ""
    link: str = ""
    summary: str = ""
    published_at: datetime
    fetched_at: datetime


class AgentFinding(BaseModel):
    agent: str
    score: int = Field(ge=1, le=5)
    rationale: str
    signals: list[str] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)


class ThreatAssessment(BaseModel):
    article_id: str
    overall_score: int = Field(ge=1, le=5)
    severity_label: str
    affected_areas: list[str]
    impact_summary: str
    recommended_action: str
    agent_findings: list[AgentFinding]
    assessed_at: datetime


class DashboardPayload(BaseModel):
    generated_at: datetime
    refresh_minutes: int
    article_count: int
    high_threat_count: int
    assessments: list[dict[str, Any]]
