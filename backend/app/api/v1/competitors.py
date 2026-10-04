import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.enums import PRIORITY_RANK, Priority, Role
from app.db.models import (
    CompanyProfile,
    Competitor,
    CompetitorProduct,
    CompetitorRelationship,
    Event,
    PricePoint,
    ProductFeature,
    Source,
)
from app.deps import Principal, get_db, get_principal, require_roles
from app.schemas.dto import (
    CompetitorIn,
    CompetitorListItem,
    CompetitorOut,
    CompetitorProductOut,
    CompetitorUpdate,
    EventOut,
    GraphEdge,
    GraphNode,
    PricePointOut,
    ProductFeatureOut,
    RelationshipGraph,
    RelationshipIn,
    RelationshipOut,
)

router = APIRouter(prefix="/competitors", tags=["competitors"])
graph_router = APIRouter(tags=["competitors"])
editor = Depends(require_roles(Role.executive, Role.product, Role.marketing, Role.pricing))


async def _get(db: AsyncSession, competitor_id: uuid.UUID) -> Competitor:
    c = await db.get(Competitor, competitor_id)
    if not c:
        raise HTTPException(404, "Competitor not found")
    return c


@router.get("", response_model=list[CompetitorListItem])
async def list_competitors(db: AsyncSession = Depends(get_db)):
    since = utcnow() - timedelta(days=30)
    comps = list(
        (
            await db.execute(select(Competitor).order_by(Competitor.threat_tier.desc(), Competitor.name))
        ).scalars()
    )
    src_counts = dict(
        (await db.execute(select(Source.competitor_id, func.count()).group_by(Source.competitor_id))).all()
    )
    ev_rows = (
        await db.execute(
            select(Event.competitor_id, Event.priority, func.count(), func.max(Event.detected_at))
            .where(Event.detected_at >= since, Event.priority.is_not(None))
            .group_by(Event.competitor_id, Event.priority)
        )
    ).all()
    agg: dict[uuid.UUID, dict] = {}
    for cid, prio, n, last in ev_rows:
        a = agg.setdefault(cid, {"events_30d": 0, "last_event_at": None, "top": None})
        a["events_30d"] += n
        a["last_event_at"] = max(filter(None, [a["last_event_at"], last]), default=None)
        if prio and (a["top"] is None or PRIORITY_RANK[Priority(prio)] > PRIORITY_RANK[Priority(a["top"])]):
            a["top"] = prio
    out = []
    for c in comps:
        a = agg.get(c.id, {})
        out.append(
            CompetitorListItem(
                **CompetitorOut.model_validate(c).model_dump(),
                source_count=src_counts.get(c.id, 0),
                events_30d=a.get("events_30d", 0),
                last_event_at=a.get("last_event_at"),
                top_priority_30d=a.get("top"),
            )
        )
    return out


@router.post("", response_model=CompetitorOut, status_code=201, dependencies=[editor])
async def create_competitor(
    body: CompetitorIn, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    c = Competitor(org_id=p.org_id, **body.model_dump())
    c.domain = c.domain.lower().removeprefix("https://").removeprefix("http://").strip("/")
    db.add(c)
    try:
        await db.commit()
    except IntegrityError as e:
        raise HTTPException(409, "A competitor with this name already exists") from e
    await db.refresh(c)
    return c


@router.get("/{competitor_id}", response_model=CompetitorOut)
async def get_competitor(competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await _get(db, competitor_id)


@router.patch("/{competitor_id}", response_model=CompetitorOut, dependencies=[editor])
async def update_competitor(
    competitor_id: uuid.UUID, body: CompetitorUpdate, db: AsyncSession = Depends(get_db)
):
    c = await _get(db, competitor_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return c


@router.delete("/{competitor_id}", status_code=204, dependencies=[editor])
async def delete_competitor(competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    c = await _get(db, competitor_id)
    await db.delete(c)
    await db.commit()


@router.get("/{competitor_id}/timeline", response_model=list[EventOut])
async def timeline(
    competitor_id: uuid.UUID, limit: int = Query(100, le=500), db: AsyncSession = Depends(get_db)
):
    c = await _get(db, competitor_id)
    events = (
        await db.execute(
            select(Event)
            .where(Event.competitor_id == competitor_id)
            .order_by(Event.detected_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [EventOut.model_validate(e).model_copy(update={"competitor_name": c.name}) for e in events]


@router.get("/{competitor_id}/pricing-history", response_model=list[PricePointOut])
async def pricing_history(competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get(db, competitor_id)
    return list(
        (
            await db.execute(
                select(PricePoint)
                .where(PricePoint.competitor_id == competitor_id)
                .order_by(PricePoint.plan, PricePoint.valid_from)
            )
        ).scalars()
    )


@router.get("/{competitor_id}/products", response_model=list[CompetitorProductOut])
async def products(competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get(db, competitor_id)
    prods = list(
        (
            await db.execute(
                select(CompetitorProduct)
                .where(CompetitorProduct.competitor_id == competitor_id)
                .order_by(CompetitorProduct.name)
            )
        ).scalars()
    )
    feats = list(
        (
            await db.execute(
                select(ProductFeature).where(
                    ProductFeature.product_id.in_([p.id for p in prods] or [uuid.uuid4()])
                )
            )
        ).scalars()
    )
    by_prod: dict[uuid.UUID, list] = {}
    for f in feats:
        by_prod.setdefault(f.product_id, []).append(ProductFeatureOut.model_validate(f))
    return [
        CompetitorProductOut.model_validate(p).model_copy(update={"features": by_prod.get(p.id, [])})
        for p in prods
    ]


@router.get("/{competitor_id}/relationships", response_model=list[RelationshipOut])
async def relationships(competitor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get(db, competitor_id)
    return list(
        (
            await db.execute(
                select(CompetitorRelationship).where(CompetitorRelationship.competitor_id == competitor_id)
            )
        ).scalars()
    )


@router.post(
    "/{competitor_id}/relationships", response_model=RelationshipOut, status_code=201, dependencies=[editor]
)
async def add_relationship(
    competitor_id: uuid.UUID,
    body: RelationshipIn,
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    await _get(db, competitor_id)
    other = (
        await db.execute(
            select(Competitor.id).where(func.lower(Competitor.name) == body.counterparty_name.lower())
        )
    ).scalar_one_or_none()
    row = CompetitorRelationship(
        org_id=p.org_id,
        competitor_id=competitor_id,
        counterparty_name=body.counterparty_name,
        counterparty_competitor_id=other,
        rel_type=body.rel_type.value,
        description=body.description,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as e:
        raise HTTPException(409, "Relationship already exists") from e
    await db.refresh(row)
    return row


@graph_router.get("/relationship-graph", response_model=RelationshipGraph)
async def relationship_graph(db: AsyncSession = Depends(get_db)):
    """Org-wide relationship graph: us, competitors, and their partners/investors/acquisitions."""
    company = (await db.execute(select(CompanyProfile).limit(1))).scalar_one_or_none()
    comps = list((await db.execute(select(Competitor))).scalars())
    rels = list((await db.execute(select(CompetitorRelationship))).scalars())
    nodes = {"us": GraphNode(id="us", label=company.name if company else "Us", kind="us")}
    edges = []
    for c in comps:
        nodes[str(c.id)] = GraphNode(id=str(c.id), label=c.name, kind="competitor")
        edges.append(GraphEdge(id=f"us-{c.id}", source=str(c.id), target="us", label="competes with"))
    for r in rels:
        target = (
            str(r.counterparty_competitor_id)
            if r.counterparty_competitor_id
            else f"org:{r.counterparty_name.lower()}"
        )
        if target not in nodes:
            nodes[target] = GraphNode(id=target, label=r.counterparty_name, kind="organization")
        edges.append(GraphEdge(id=str(r.id), source=str(r.competitor_id), target=target, label=r.rel_type))
    return RelationshipGraph(nodes=list(nodes.values()), edges=edges)
