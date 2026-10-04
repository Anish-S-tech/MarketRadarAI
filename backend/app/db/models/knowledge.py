"""Persistent competitive memory: profiles, products, pricing history, relationships, semantic chunks."""

import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin, utcnow


class Competitor(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_competitors_org_name"),)

    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    threat_tier: Mapped[int] = mapped_column(Integer, default=3)  # 1 (minor) .. 5 (primary rival)
    segments: Mapped[list] = mapped_column(JSONB, default=list)
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")  # rolling LLM-maintained profile summary
    ticker: Mapped[str | None] = mapped_column(String(16))
    cik: Mapped[str | None] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CompetitorProduct(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "competitor_products"
    __table_args__ = (UniqueConstraint("competitor_id", "name", name="uq_competitor_products_comp_name"),)

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))


class ProductFeature(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "product_features"
    __table_args__ = (UniqueConstraint("product_id", "name", name="uq_product_features_product_name"),)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitor_products.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PricePoint(IdMixin, TimestampMixin, TenantMixin, Base):
    """Price history as SCD-2 rows: the current price for a plan has valid_to = NULL."""

    __tablename__ = "price_points"
    __table_args__ = (Index("ix_price_points_comp_plan", "competitor_id", "plan", "valid_to"),)

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitor_products.id", ondelete="SET NULL")
    )
    plan: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    period: Mapped[str] = mapped_column(String(32), default="month")
    features: Mapped[list] = mapped_column(JSONB, default=list)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL")
    )


class CompetitorRelationship(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "competitor_relationships"
    __table_args__ = (
        UniqueConstraint(
            "competitor_id", "counterparty_name", "rel_type", name="uq_competitor_relationships_triple"
        ),
    )

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    counterparty_name: Mapped[str] = mapped_column(String(200))
    counterparty_competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL")
    )
    rel_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))


class KBChunk(IdMixin, TimestampMixin, TenantMixin, Base):
    """Semantic memory: embedded text from events, evidence, snapshots, profiles and briefs."""

    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_kb_chunks_ref", "kind", "ref_id"),
    )

    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # event | evidence | snapshot | profile | brief
    ref_id: Mapped[uuid.UUID | None] = mapped_column()
    title: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embed_dim))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(title,'') || ' ' || content)", persisted=True)
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
