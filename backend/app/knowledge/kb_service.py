"""Writes to the persistent competitive memory: pricing history (SCD-2), products, features,
relationships and embedded semantic chunks."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import (
    Competitor,
    CompetitorProduct,
    CompetitorRelationship,
    Event,
    KBChunk,
    PricePoint,
    ProductFeature,
)
from app.llm.client import get_llm
from app.llm.schemas import ExtractedProduct, ExtractedRelationship


async def add_chunks(db: AsyncSession, org_id: uuid.UUID, chunks: list[dict[str, Any]]) -> list[KBChunk]:
    """chunks: [{kind, ref_id, title, content, competitor_id?, meta?, occurred_at?}]. Embeds in one batch."""
    chunks = [c for c in chunks if c.get("content", "").strip()]
    if not chunks:
        return []
    vectors = await get_llm().embed([f"{c.get('title', '')}\n{c['content']}" for c in chunks])
    rows = []
    for i, c in enumerate(chunks):
        row = KBChunk(
            org_id=org_id,
            competitor_id=c.get("competitor_id"),
            kind=c["kind"],
            ref_id=c.get("ref_id"),
            title=c.get("title", "")[:500],
            content=c["content"][:20000],
            embedding=vectors[i] if vectors else None,
            meta=c.get("meta", {}),
            occurred_at=c.get("occurred_at") or utcnow(),
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows


def _dec(v: float | None) -> Decimal | None:
    return None if v is None else Decimal(str(round(v, 2)))


async def sync_price_points(
    db: AsyncSession,
    org_id: uuid.UUID,
    competitor_id: uuid.UUID,
    plans: list[dict[str, Any]],
    *,
    event_id: uuid.UUID | None = None,
    snapshot_id: uuid.UUID | None = None,
    observed_at: datetime | None = None,
) -> dict[str, int]:
    """Apply the currently observed pricing table as SCD-2 history. Returns counts of opened/closed rows."""
    now = observed_at or utcnow()
    current = (
        (
            await db.execute(
                select(PricePoint).where(
                    PricePoint.competitor_id == competitor_id, PricePoint.valid_to.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    by_plan = {p.plan.lower().strip(): p for p in current}
    seen: set[str] = set()
    opened = closed = 0
    for plan in plans:
        key = plan["name"].lower().strip()
        seen.add(key)
        price = _dec(plan.get("price"))
        existing = by_plan.get(key)
        if existing and existing.price == price and existing.period == plan.get("period", "month"):
            existing.features = plan.get("features", [])
            continue
        if existing:
            existing.valid_to = now
            closed += 1
        db.add(
            PricePoint(
                org_id=org_id,
                competitor_id=competitor_id,
                plan=plan["name"],
                price=price,
                currency=plan.get("currency", "USD"),
                period=plan.get("period", "month"),
                features=plan.get("features", []),
                valid_from=now,
                source_event_id=event_id,
                source_snapshot_id=snapshot_id,
            )
        )
        opened += 1
    for key, row in by_plan.items():
        if key not in seen:
            row.valid_to = now
            closed += 1
    await db.flush()
    return {"opened": opened, "closed": closed}


async def upsert_products(
    db: AsyncSession,
    org_id: uuid.UUID,
    competitor_id: uuid.UUID,
    products: list[ExtractedProduct],
    event_id: uuid.UUID | None = None,
) -> int:
    count = 0
    now = utcnow()
    for p in products:
        name = p.name.strip()[:200]
        if not name:
            continue
        row = (
            await db.execute(
                select(CompetitorProduct).where(
                    CompetitorProduct.competitor_id == competitor_id,
                    func.lower(CompetitorProduct.name) == name.lower(),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = CompetitorProduct(
                org_id=org_id,
                competitor_id=competitor_id,
                name=name,
                description=p.description[:2000],
                category=p.category[:100],
                source_event_id=event_id,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(row)
            await db.flush()
            count += 1
        else:
            row.last_seen_at = now
            if p.description and not row.description:
                row.description = p.description[:2000]
        existing = {
            f.lower()
            for f in (
                await db.execute(select(ProductFeature.name).where(ProductFeature.product_id == row.id))
            ).scalars()
        }
        for feat in p.features[:30]:
            if feat.strip() and feat.lower().strip() not in existing:
                db.add(ProductFeature(org_id=org_id, product_id=row.id, name=feat.strip()[:300]))
                existing.add(feat.lower().strip())
    await db.flush()
    return count


async def upsert_relationships(
    db: AsyncSession,
    org_id: uuid.UUID,
    competitor_id: uuid.UUID,
    rels: list[ExtractedRelationship],
    event_id: uuid.UUID | None = None,
) -> int:
    count = 0
    known = {
        c.name.lower(): c.id
        for c in (await db.execute(select(Competitor).where(Competitor.org_id == org_id))).scalars()
    }
    for r in rels:
        name = r.counterparty.strip()[:200]
        if not name:
            continue
        exists = (
            await db.execute(
                select(CompetitorRelationship.id).where(
                    CompetitorRelationship.competitor_id == competitor_id,
                    func.lower(CompetitorRelationship.counterparty_name) == name.lower(),
                    CompetitorRelationship.rel_type == r.rel_type,
                )
            )
        ).scalar_one_or_none()
        if exists:
            continue
        db.add(
            CompetitorRelationship(
                org_id=org_id,
                competitor_id=competitor_id,
                counterparty_name=name,
                counterparty_competitor_id=known.get(name.lower()),
                rel_type=r.rel_type,
                description=r.description[:2000],
                source_event_id=event_id,
            )
        )
        count += 1
    await db.flush()
    return count


async def recent_history(
    db: AsyncSession, competitor_id: uuid.UUID, limit: int = 8, exclude_event_id: uuid.UUID | None = None
) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.competitor_id == competitor_id)
        .order_by(Event.detected_at.desc())
        .limit(limit)
    )
    if exclude_event_id:
        stmt = stmt.where(Event.id != exclude_event_id)
    return list((await db.execute(stmt)).scalars())
