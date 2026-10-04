import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin, utcnow


class Change(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "changes"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    prev_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL")
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), default="diff")  # diff | new_item | pricing
    diff: Mapped[dict] = mapped_column(JSONB, default=dict)
    category: Mapped[str] = mapped_column(String(32), default="other")
    significance: Mapped[float] = mapped_column(Float, default=0.0)
    title: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    key_facts: Mapped[list] = mapped_column(JSONB, default=list)
    is_significant: Mapped[bool] = mapped_column(Boolean, default=False)


class Event(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_org_detected", "org_id", "detected_at"),
        Index("ix_events_dedupe", "org_id", "dedupe_key"),
    )

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    change_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("changes.id", ondelete="SET NULL"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32))
    key_facts: Mapped[list] = mapped_column(JSONB, default=list)
    priority: Mapped[str | None] = mapped_column(String(16), index=True)
    priority_score: Mapped[float | None] = mapped_column(Float)
    priority_factors: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence_level: Mapped[str | None] = mapped_column(String(16))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="new")
    stage: Mapped[str] = mapped_column(String(32), default="detected")  # pipeline progress
    dedupe_key: Mapped[str] = mapped_column(String(200))
    # True for events that originate from a simulated feed (demo scenarios) — always shown as such.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))


class Evidence(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "evidence"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    domain: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(32), default="web")  # primary | monitored | web | news | kb
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reliability_tier: Mapped[int] = mapped_column(Integer, default=3)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    stances: Mapped[list] = mapped_column(JSONB, default=list)  # [{claim_index, stance, rationale}]


class Verification(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "verifications"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), unique=True)
    confidence_score: Mapped[float] = mapped_column(Float)
    level: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text, default="")
    claims: Mapped[list] = mapped_column(JSONB, default=list)


class ImpactAssessment(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "impact_assessments"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), unique=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    overall_severity: Mapped[int] = mapped_column(Integer, default=1)
    dimensions: Mapped[dict] = mapped_column(JSONB, default=dict)
    affected_products: Mapped[list] = mapped_column(JSONB, default=list)
    affected_segments: Mapped[list] = mapped_column(JSONB, default=list)
    role_implications: Mapped[dict] = mapped_column(JSONB, default=dict)
    recommended_actions: Mapped[list] = mapped_column(JSONB, default=list)
    priority_rationale: Mapped[str] = mapped_column(Text, default="")
