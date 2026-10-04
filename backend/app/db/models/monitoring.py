import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Computed

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin, utcnow


class Source(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (Index("ix_sources_due", "is_active", "next_check_at"),)

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(2000))
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    render_js: Mapped[bool] = mapped_column(Boolean, default=False)
    include_selectors: Mapped[list] = mapped_column(JSONB, default=list)
    ignore_selectors: Mapped[list] = mapped_column(JSONB, default=list)
    significance_threshold: Mapped[float | None] = mapped_column(Float)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    etag: Mapped[str | None] = mapped_column(String(500))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class Snapshot(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        Index("ix_snapshots_source_fetched", "source_id", "fetched_at"),
        Index("ix_snapshots_tsv", "tsv", postgresql_using="gin"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    content_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(500), default="")
    structured: Mapped[dict] = mapped_column(JSONB, default=dict)  # pricing tables, feed items, filings
    blob_key: Mapped[str | None] = mapped_column(String(500))
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetch_method: Mapped[str] = mapped_column(String(32), default="http")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(title,'') || ' ' || left(text, 200000))", persisted=True),
    )
