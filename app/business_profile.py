from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessArea:
    name: str
    description: str
    keywords: tuple[str, ...]


COMPANY_NAME = "Thirs Horizon Strategies"

BUSINESS_AREAS: tuple[BusinessArea, ...] = (
    BusinessArea(
        name="Policy and regulatory advisory",
        description="Work tied to federal/state health policy, reimbursement rules, Medicaid, Medicare, and compliance strategy.",
        keywords=(
            "medicaid",
            "medicare",
            "cms",
            "hhs",
            "regulation",
            "regulatory",
            "policy",
            "reimbursement",
            "rate",
            "rule",
            "compliance",
            "waiver",
            "aco",
            "aca",
        ),
    ),
    BusinessArea(
        name="Payer and provider strategy",
        description="Advisory work for health plans, provider organizations, networks, and market positioning.",
        keywords=(
            "payer",
            "provider",
            "hospital",
            "health system",
            "insurance",
            "insurer",
            "unitedhealth",
            "cigna",
            "humana",
            "elevance",
            "molina",
            "centene",
            "network",
            "contract",
        ),
    ),
    BusinessArea(
        name="Value-based care and transformation",
        description="Programs connected to risk contracts, care delivery redesign, outcomes, affordability, and quality.",
        keywords=(
            "value-based",
            "risk",
            "outcomes",
            "quality",
            "affordability",
            "care management",
            "population health",
            "utilization",
            "prior authorization",
            "primary care",
            "behavioral health",
        ),
    ),
    BusinessArea(
        name="Market intelligence and growth",
        description="Competitive intelligence, M&A monitoring, go-to-market planning, and opportunity sizing.",
        keywords=(
            "acquisition",
            "merger",
            "deal",
            "partnership",
            "growth",
            "market",
            "competition",
            "forecast",
            "guidance",
            "earnings",
            "revenue",
            "margin",
            "profit",
        ),
    ),
    BusinessArea(
        name="Client reputation and strategic communications",
        description="Messaging and stakeholder strategy when controversy, lawsuits, cyber incidents, or access issues hit clients.",
        keywords=(
            "lawsuit",
            "investigation",
            "probe",
            "fraud",
            "breach",
            "cyber",
            "outage",
            "strike",
            "controversy",
            "criticism",
            "patient safety",
            "recall",
        ),
    ),
)
