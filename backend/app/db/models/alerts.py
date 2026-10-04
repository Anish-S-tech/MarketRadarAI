import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin, utcnow


class AlertSubscription(IdMixin, TimestampMixin, TenantMixin, Base):
    """Routes events to people. Either role-wide (user_id NULL) or personal (user_id set)."""

    __tablename__ = "alert_subscriptions"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200), default="")
    categories: Mapped[list] = mapped_column(JSONB, default=list)  # empty = all
    competitor_ids: Mapped[list] = mapped_column(JSONB, default=list)  # empty = all
    min_priority: Mapped[str] = mapped_column(String(16), default="medium")
    channels: Mapped[list] = mapped_column(JSONB, default=lambda: ["in_app", "email"])
    include_in_brief: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_user_created", "user_id", "created_at"),
        UniqueConstraint("user_id", "event_id", "channel", name="uq_alerts_user_event_channel"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    priority: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(500))
    body_md: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Brief(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "briefs"
    __table_args__ = (UniqueConstraint("org_id", "brief_date", "role", name="uq_briefs_org_date_role"),)

    brief_date: Mapped[date] = mapped_column(Date)
    role: Mapped[str] = mapped_column(String(32))  # "general" or a Role
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    content_md: Mapped[str] = mapped_column(Text, default="")
    content_html: Mapped[str] = mapped_column(Text, default="")
    event_ids: Mapped[list] = mapped_column(JSONB, default=list)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
