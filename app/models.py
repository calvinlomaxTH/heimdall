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
    created_at: datetime | None = None
    updated_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    reviewed: bool = False
    analyst_notes: str = ""


class AgentFinding(BaseModel):
    agent: str
    score: int = Field(ge=1, le=5)
    rationale: str
    signals: list[str] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)
    confidence: str = "low"
    risk_categories: list[str] = Field(default_factory=list)
    recommended_action: str = ""


class ThreatAssessment(BaseModel):
    article_id: str
    overall_score: int = Field(ge=1, le=5)
    severity_label: str
    affected_areas: list[str]
    risk_categories: list[str] = Field(default_factory=list)
    detected_signals: list[str] = Field(default_factory=list)
    confidence: str = "low"
    impact_summary: str
    recommended_action: str
    agent_findings: list[AgentFinding]
    assessed_at: datetime


class DashboardPayload(BaseModel):
    generated_at: datetime
    refresh_minutes: int
    next_refresh_at: datetime | None = None
    last_successful_refresh_at: datetime | None = None
    article_count: int
    high_threat_count: int
    assessments: list[dict[str, Any]]
    high_priority: list[dict[str, Any]] = Field(default_factory=list)
    recently_added: list[dict[str, Any]] = Field(default_factory=list)


class ArticlePatch(BaseModel):
    reviewed: bool | None = None
    analyst_notes: str | None = None


class TickerPayload(BaseModel):
    symbol: str = Field(min_length=1, max_length=12)
    enabled: bool = True


class TickerPatch(BaseModel):
    symbol: str | None = Field(default=None, min_length=1, max_length=12)
    enabled: bool | None = None


class ConfigPatch(BaseModel):
    refresh_minutes: int | None = Field(default=None, ge=5, le=1440)
    lookback_hours: int | None = Field(default=None, ge=1, le=720)


class RefreshRun(BaseModel):
    run_id: int
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    tickers_checked: int = 0
    articles_fetched: int = 0
    new_articles_inserted: int = 0
    articles_assessed: int = 0
    errors: str = ""


class AnalyticsPayload(BaseModel):
    generated_at: datetime
    summary: dict[str, Any]
    threat_counts_by_day: list[dict[str, Any]]
    threats_by_ticker: list[dict[str, Any]]
    threats_by_area: list[dict[str, Any]]
    threats_by_risk_category: list[dict[str, Any]]
