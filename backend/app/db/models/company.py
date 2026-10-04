import uuid
from decimal import Decimal

from sqlalchemy import Float, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class CompanyProfile(IdMixin, TimestampMixin, TenantMixin, Base):
    """Our own company — the lens through which the Impact Agent evaluates competitor moves."""

    __tablename__ = "company_profile"

    name: Mapped[str] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    positioning: Mapped[str] = mapped_column(Text, default="")
    differentiators: Mapped[list] = mapped_column(JSONB, default=list)
    target_markets: Mapped[list] = mapped_column(JSONB, default=list)


class OwnProduct(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "own_products"

    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    features: Mapped[list] = mapped_column(JSONB, default=list)


class OwnPricePoint(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "own_price_points"

    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("own_products.id", ondelete="CASCADE"))
    plan: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    period: Mapped[str] = mapped_column(String(32), default="month")


class CustomerSegment(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "customer_segments"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    revenue_share: Mapped[float] = mapped_column(Float, default=0.0)
