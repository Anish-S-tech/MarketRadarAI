"""Structured-output contracts for every LLM task. Validators clamp values instead of failing,
because small local models often drift slightly outside numeric bounds."""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.db.enums import ChangeCategory


def _clamp(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


class ChangeClassification(BaseModel):
    is_meaningful: bool = Field(
        description="False for cosmetic, boilerplate, navigation or date-only changes"
    )
    category: ChangeCategory
    significance: float = Field(description="0.0 (trivial) to 1.0 (major strategic move)")
    title: str = Field(description="Headline under 15 words, naming the competitor")
    summary: str = Field(description="2-3 sentence factual summary of what changed")
    key_facts: list[str] = Field(
        default_factory=list, description="Concrete, checkable facts (numbers, names)"
    )

    @field_validator("significance", mode="before")
    @classmethod
    def _sig(cls, v: Any) -> float:
        return _clamp(v, 0.0, 1.0, 0.3)

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v: Any) -> str:
        v = str(v).lower().strip()
        return v if v in ChangeCategory.__members__ else "other"


class PricingPlan(BaseModel):
    name: str
    price: float | None = Field(default=None, description="Numeric price, null for 'Contact sales' / custom")
    currency: str = "USD"
    period: str = Field(default="month", description="month | year | one-time | usage")
    features: list[str] = Field(default_factory=list)

    @field_validator("price", mode="before")
    @classmethod
    def _price(cls, v: Any) -> float | None:
        if v in (None, "", "null"):
            return None
        try:
            return float(str(v).replace("$", "").replace(",", "").strip())
        except ValueError:
            return None


class PricingTable(BaseModel):
    plans: list[PricingPlan] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    claims: list[str] = Field(description="Atomic factual claims to verify, most important first")
    queries: list[str] = Field(description="Web search queries that could confirm or refute the claims")


class ClaimJudgment(BaseModel):
    claim_index: int
    stance: Literal["supports", "contradicts", "irrelevant"]
    rationale: str = ""

    @field_validator("stance", mode="before")
    @classmethod
    def _stance(cls, v: Any) -> str:
        v = str(v).lower().strip()
        return v if v in {"supports", "contradicts", "irrelevant"} else "irrelevant"


class EvidenceJudgment(BaseModel):
    judgments: list[ClaimJudgment] = Field(default_factory=list)


class ExtractedProduct(BaseModel):
    name: str
    description: str = ""
    category: str = ""
    features: list[str] = Field(default_factory=list)


_TRAILING = re.compile(
    r"\s+(?:to|and|for|in|on|that|which|who|as|with|by|from|at|after|amid|while|launch(?:es|ed)?|announc\w*)(?=\W|$).*$",
    re.I,
)


def clean_org_name(name: str) -> str:
    """'Snowflake to launch Globex Connect' -> 'Snowflake'."""
    return _TRAILING.sub("", name.strip()).strip(" .,;:'\"")[:200]


class ExtractedRelationship(BaseModel):
    counterparty: str

    @field_validator("counterparty", mode="before")
    @classmethod
    def _cp(cls, v: Any) -> str:
        return clean_org_name(str(v))

    rel_type: Literal[
        "partner", "investor", "acquirer", "acquired", "integration", "customer", "supplier", "competitor"
    ]
    description: str = ""

    @field_validator("rel_type", mode="before")
    @classmethod
    def _rt(cls, v: Any) -> str:
        v = str(v).lower().strip()
        allowed = {
            "partner",
            "investor",
            "acquirer",
            "acquired",
            "integration",
            "customer",
            "supplier",
            "competitor",
        }
        return v if v in allowed else "partner"


class EntityExtraction(BaseModel):
    products: list[ExtractedProduct] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


class DimensionImpact(BaseModel):
    severity: int = Field(description="1 negligible .. 5 severe")
    rationale: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, v: Any) -> int:
        return int(round(_clamp(v, 1, 5, 2)))


class RoleImplications(BaseModel):
    executive: str = ""
    product: str = ""
    sales: str = ""
    marketing: str = ""
    pricing: str = ""


class RecommendedAction(BaseModel):
    action: str
    owner_role: Literal["executive", "product", "sales", "marketing", "pricing"] = "executive"
    urgency: Literal["immediate", "this_week", "this_quarter"] = "this_week"

    @field_validator("owner_role", mode="before")
    @classmethod
    def _role(cls, v: Any) -> str:
        v = str(v).lower().strip()
        return v if v in {"executive", "product", "sales", "marketing", "pricing"} else "executive"

    @field_validator("urgency", mode="before")
    @classmethod
    def _urg(cls, v: Any) -> str:
        v = str(v).lower().strip().replace(" ", "_")
        return v if v in {"immediate", "this_week", "this_quarter"} else "this_week"


class ImpactAnalysis(BaseModel):
    summary: str
    products: DimensionImpact
    customers: DimensionImpact
    pricing: DimensionImpact
    competitive_position: DimensionImpact
    affected_products: list[str] = Field(default_factory=list)
    affected_segments: list[str] = Field(default_factory=list)
    role_implications: RoleImplications = Field(default_factory=RoleImplications)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)

    @property
    def max_severity(self) -> int:
        return max(
            self.products.severity,
            self.customers.severity,
            self.pricing.severity,
            self.competitive_position.severity,
        )


class BriefSummary(BaseModel):
    headline: str
    executive_summary: str
    key_themes: list[str] = Field(default_factory=list)
    watch_list: list[str] = Field(default_factory=list)


class CompetitorSummary(BaseModel):
    summary: str
