"""API request/response models."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.enums import ChangeCategory, EventStatus, Priority, RelationshipType, Role, SourceType
from app.monitoring.netsafety import validate_url_syntax

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------- auth ----------------
class RegisterIn(BaseModel):
    org_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(ORM):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class AuthConfigOut(BaseModel):
    allow_signup: bool
    oidc_enabled: bool
    oidc_name: str


# ---------------- users / keys / org ----------------
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: Role
    password: str = Field(min_length=10, max_length=200)


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: Role = Role.executive


class ApiKeyOut(ORM):
    id: uuid.UUID
    name: str
    prefix: str
    role: Role
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    key: str


class OrgOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    brief_hour_utc: int
    settings: dict[str, Any]


class OrgUpdate(BaseModel):
    name: str | None = None
    brief_hour_utc: int | None = Field(default=None, ge=0, le=23)
    settings: dict[str, Any] | None = None


# ---------------- company ----------------
class CompanyProfileIn(BaseModel):
    name: str
    website: str | None = None
    description: str = ""
    positioning: str = ""
    differentiators: list[str] = []
    target_markets: list[str] = []


class CompanyProfileOut(CompanyProfileIn, ORM):
    id: uuid.UUID


class OwnProductIn(BaseModel):
    name: str
    category: str = ""
    description: str = ""
    features: list[str] = []


class OwnProductOut(OwnProductIn, ORM):
    id: uuid.UUID


class OwnPriceIn(BaseModel):
    product_id: uuid.UUID | None = None
    plan: str
    price: Decimal | None = None
    currency: str = "USD"
    period: str = "month"


class OwnPriceOut(OwnPriceIn, ORM):
    id: uuid.UUID


class SegmentIn(BaseModel):
    name: str
    description: str = ""
    revenue_share: float = Field(default=0.0, ge=0, le=1)


class SegmentOut(SegmentIn, ORM):
    id: uuid.UUID


# ---------------- competitors ----------------
class CompetitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=3, max_length=255)
    description: str = ""
    threat_tier: int = Field(default=3, ge=1, le=5)
    segments: list[str] = []
    aliases: list[str] = []
    ticker: str | None = None
    cik: str | None = None
    is_active: bool = True


class CompetitorUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    description: str | None = None
    threat_tier: int | None = Field(default=None, ge=1, le=5)
    segments: list[str] | None = None
    aliases: list[str] | None = None
    ticker: str | None = None
    cik: str | None = None
    is_active: bool | None = None


class CompetitorOut(ORM):
    id: uuid.UUID
    name: str
    domain: str
    description: str
    threat_tier: int
    segments: list[str]
    aliases: list[str]
    summary: str
    ticker: str | None
    cik: str | None
    is_active: bool
    created_at: datetime


class CompetitorListItem(CompetitorOut):
    source_count: int = 0
    events_30d: int = 0
    last_event_at: datetime | None = None
    top_priority_30d: Priority | None = None


class ProductFeatureOut(ORM):
    id: uuid.UUID
    name: str
    first_seen_at: datetime
    removed_at: datetime | None


class CompetitorProductOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    category: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    features: list[ProductFeatureOut] = []


class PricePointOut(ORM):
    id: uuid.UUID
    plan: str
    price: Decimal | None
    currency: str
    period: str
    features: list[str]
    valid_from: datetime
    valid_to: datetime | None
    source_event_id: uuid.UUID | None


class RelationshipIn(BaseModel):
    counterparty_name: str
    rel_type: RelationshipType
    description: str = ""


class RelationshipOut(ORM):
    id: uuid.UUID
    competitor_id: uuid.UUID
    counterparty_name: str
    counterparty_competitor_id: uuid.UUID | None
    rel_type: str
    description: str
    first_seen_at: datetime
    source_event_id: uuid.UUID | None


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str  # competitor | organization | us


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str


class RelationshipGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ---------------- sources / snapshots ----------------
class SourceIn(BaseModel):
    competitor_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    url: str = Field(default="", max_length=2000)
    check_interval_minutes: int = Field(default=360, ge=5, le=10080)
    render_js: bool = False
    include_selectors: list[str] = []
    ignore_selectors: list[str] = []
    significance_threshold: float | None = Field(default=None, ge=0, le=1)
    config: dict[str, Any] = {}
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return validate_url_syntax(v) if v else v


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    check_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    render_js: bool | None = None
    include_selectors: list[str] | None = None
    ignore_selectors: list[str] | None = None
    significance_threshold: float | None = Field(default=None, ge=0, le=1)
    config: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return validate_url_syntax(v) if v else v


class SourceOut(ORM):
    id: uuid.UUID
    competitor_id: uuid.UUID
    name: str
    source_type: SourceType
    url: str
    check_interval_minutes: int
    render_js: bool
    include_selectors: list[str]
    ignore_selectors: list[str]
    significance_threshold: float | None
    config: dict[str, Any]
    is_active: bool
    last_checked_at: datetime | None
    next_check_at: datetime
    last_status: str | None
    last_error: str | None
    consecutive_failures: int
    created_at: datetime


class SnapshotMeta(ORM):
    id: uuid.UUID
    source_id: uuid.UUID
    content_hash: str
    title: str
    http_status: int | None
    fetch_method: str
    fetched_at: datetime
    blob_key: str | None


class SnapshotOut(SnapshotMeta):
    text: str
    structured: dict[str, Any]


class SourceTestIn(BaseModel):
    source_type: SourceType
    url: str
    render_js: bool = False
    include_selectors: list[str] = []
    ignore_selectors: list[str] = []
    config: dict[str, Any] = {}


class SourceTestOut(BaseModel):
    ok: bool
    title: str = ""
    text_preview: str = ""
    chars: int = 0
    items: list[dict[str, Any]] = []
    fetch_method: str = ""
    error: str | None = None


class CheckQueued(BaseModel):
    queued: bool
    idempotency_key: str


# ---------------- events ----------------
class EventOut(ORM):
    id: uuid.UUID
    competitor_id: uuid.UUID
    source_id: uuid.UUID | None
    title: str
    summary: str
    category: ChangeCategory
    key_facts: list[str]
    priority: Priority | None
    priority_score: float | None
    confidence_level: str | None
    confidence_score: float | None
    status: EventStatus
    stage: str
    detected_at: datetime
    is_simulated: bool = False
    competitor_name: str = ""


class EventUpdate(BaseModel):
    status: EventStatus


class EvidenceOut(ORM):
    id: uuid.UUID
    url: str
    domain: str
    title: str
    snippet: str
    origin: str
    published_at: datetime | None
    reliability_tier: int
    is_primary: bool
    stances: list[dict[str, Any]]


class VerificationOut(ORM):
    confidence_score: float
    level: str
    rationale: str
    claims: list[dict[str, Any]]


class ImpactOut(ORM):
    summary: str
    overall_severity: int
    dimensions: dict[str, Any]
    affected_products: list[str]
    affected_segments: list[str]
    role_implications: dict[str, str]
    recommended_actions: list[dict[str, Any]]
    priority_rationale: str


class ChangeOut(ORM):
    id: uuid.UUID
    kind: str
    diff: dict[str, Any]
    category: str
    significance: float
    title: str
    summary: str
    snapshot_id: uuid.UUID
    prev_snapshot_id: uuid.UUID | None


class AgentStepOut(ORM):
    id: uuid.UUID
    run_id: uuid.UUID
    agent: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    latency_ms: int | None
    models: list[dict[str, Any]]
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error: str | None


class EventDetail(BaseModel):
    event: EventOut
    competitor: CompetitorOut
    source: SourceOut | None
    change: ChangeOut | None
    evidence: list[EvidenceOut]
    verification: VerificationOut | None
    impact: ImpactOut | None
    steps: list[AgentStepOut]
    priority_factors: dict[str, Any]


class EventStats(BaseModel):
    window_days: int
    total: int
    by_priority: dict[str, int]
    by_category: dict[str, int]
    by_competitor: list[dict[str, Any]]
    daily: list[dict[str, Any]]
    sources_active: int
    sources_failing: int
    runs_24h: dict[str, int]


# ---------------- alerts / subscriptions / briefs ----------------
class AlertOut(ORM):
    id: uuid.UUID
    event_id: uuid.UUID
    channel: str
    priority: Priority
    title: str
    body_md: str
    status: str
    sent_at: datetime | None
    read_at: datetime | None
    created_at: datetime


class SubscriptionIn(BaseModel):
    name: str = ""
    role: Role | None = None
    personal: bool = False
    categories: list[ChangeCategory] = []
    competitor_ids: list[uuid.UUID] = []
    min_priority: Priority = Priority.medium
    channels: list[str] = ["in_app", "email"]
    include_in_brief: bool = True
    is_active: bool = True

    @field_validator("channels")
    @classmethod
    def _channels(cls, v: list[str]) -> list[str]:
        bad = set(v) - {"in_app", "email"}
        if bad:
            raise ValueError(f"unknown channels {bad}")
        return v


class SubscriptionOut(ORM):
    id: uuid.UUID
    user_id: uuid.UUID | None
    role: Role | None
    name: str
    categories: list[str]
    competitor_ids: list[str]
    min_priority: Priority
    channels: list[str]
    include_in_brief: bool
    is_active: bool


class BriefMeta(ORM):
    id: uuid.UUID
    brief_date: date
    role: str
    title: str
    summary: str
    stats: dict[str, Any]
    generated_at: datetime
    emailed_at: datetime | None


class BriefOut(BriefMeta):
    content_md: str
    content_html: str
    event_ids: list[str]


class BriefGenerateIn(BaseModel):
    brief_date: date | None = None
    window_hours: int = Field(default=24, ge=1, le=24 * 14)
    deliver: bool = False
    sync: bool = True


# ---------------- knowledge / runs / system ----------------
class KnowledgeHit(BaseModel):
    id: str
    kind: str
    ref_id: str | None
    competitor_id: str | None
    title: str
    content: str
    meta: dict[str, Any]
    occurred_at: str
    score: float
    similarity: float | None = None


class AgentRunOut(ORM):
    id: uuid.UUID
    graph: str
    source_id: uuid.UUID | None
    trigger: str
    status: str
    outcome: str | None
    attempts: int
    error: str | None
    summary: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    source_name: str | None = None


class AgentRunDetail(AgentRunOut):
    steps: list[AgentStepOut]


class LLMStatus(BaseModel):
    provider: str
    host: str
    reachable: bool
    classify_model: str
    reason_model: str
    embed_model: str
    available_models: list[str]
    missing_models: list[str]
