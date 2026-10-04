import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Date

from app.db.base import utcnow
from app.db.models import (
    AgentRun,
    AgentStep,
    Change,
    Competitor,
    Event,
    Evidence,
    ImpactAssessment,
    Source,
    Verification,
)
from app.deps import get_db
from app.schemas.dto import (
    AgentStepOut,
    ChangeOut,
    CompetitorOut,
    EventDetail,
    EventOut,
    EventStats,
    EventUpdate,
    EvidenceOut,
    ImpactOut,
    Page,
    SourceOut,
    VerificationOut,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=Page[EventOut])
async def list_events(
    priority: list[str] | None = Query(None),
    category: list[str] | None = Query(None),
    competitor_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    include_pending: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Event, Competitor.name).join(Competitor, Competitor.id == Event.competitor_id)
    if not include_pending:
        stmt = stmt.where(Event.priority.is_not(None))
    if priority:
        stmt = stmt.where(Event.priority.in_(priority))
    if category:
        stmt = stmt.where(Event.category.in_(category))
    if competitor_id:
        stmt = stmt.where(Event.competitor_id == competitor_id)
    if status:
        stmt = stmt.where(Event.status == status)
    if since:
        stmt = stmt.where(Event.detected_at >= since)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Event.title.ilike(like), Event.summary.ilike(like)))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Event.detected_at.desc()).limit(limit).offset(offset))).all()
    items = [EventOut.model_validate(e).model_copy(update={"competitor_name": name}) for e, name in rows]
    return Page[EventOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/stats", response_model=EventStats)
async def event_stats(days: int = Query(14, ge=1, le=365), db: AsyncSession = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    base = select(Event).where(Event.detected_at >= since, Event.priority.is_not(None)).subquery()
    by_priority: dict[str, int] = dict(
        (await db.execute(select(base.c.priority, func.count()).group_by(base.c.priority))).all()
    )
    by_category: dict[str, int] = dict(
        (await db.execute(select(base.c.category, func.count()).group_by(base.c.category))).all()
    )
    comp_rows = (
        await db.execute(
            select(Competitor.id, Competitor.name, func.count(base.c.id))
            .join(base, base.c.competitor_id == Competitor.id)
            .group_by(Competitor.id, Competitor.name)
            .order_by(func.count(base.c.id).desc())
        )
    ).all()
    day = cast(base.c.detected_at, Date)
    daily_rows = (
        await db.execute(
            select(day, base.c.priority, func.count()).group_by(day, base.c.priority).order_by(day)
        )
    ).all()
    daily: dict[str, dict] = {}
    for d, prio, n in daily_rows:
        daily.setdefault(
            d.isoformat(), {"date": d.isoformat(), "low": 0, "medium": 0, "high": 0, "critical": 0}
        )[prio] = n
    sources_active = (
        await db.execute(select(func.count()).select_from(Source).where(Source.is_active.is_(True)))
    ).scalar_one()
    sources_failing = (
        await db.execute(
            select(func.count())
            .select_from(Source)
            .where(Source.is_active.is_(True), Source.consecutive_failures > 0)
        )
    ).scalar_one()
    runs = dict(
        (
            await db.execute(
                select(AgentRun.status, func.count())
                .where(AgentRun.started_at >= utcnow() - timedelta(hours=24))
                .group_by(AgentRun.status)
            )
        ).all()
    )
    return EventStats(
        window_days=days,
        total=sum(by_priority.values()),
        by_priority=by_priority,
        by_category=by_category,
        by_competitor=[{"competitor_id": str(i), "name": n, "count": c} for i, n, c in comp_rows],
        daily=list(daily.values()),
        sources_active=sources_active,
        sources_failing=sources_failing,
        runs_24h=runs,
    )


@router.get("/{event_id}", response_model=EventDetail)
async def get_event(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    competitor = await db.get(Competitor, event.competitor_id)
    source = await db.get(Source, event.source_id) if event.source_id else None
    change = await db.get(Change, event.change_id) if event.change_id else None
    evidence = list(
        (
            await db.execute(
                select(Evidence)
                .where(Evidence.event_id == event_id)
                .order_by(Evidence.is_primary.desc(), Evidence.reliability_tier)
            )
        ).scalars()
    )
    verification = (
        await db.execute(select(Verification).where(Verification.event_id == event_id))
    ).scalar_one_or_none()
    impact = (
        await db.execute(select(ImpactAssessment).where(ImpactAssessment.event_id == event_id))
    ).scalar_one_or_none()
    steps: list[AgentStep] = []
    if event.agent_run_id:
        steps = list(
            (
                await db.execute(
                    select(AgentStep)
                    .where(
                        AgentStep.run_id == event.agent_run_id,
                        or_(
                            AgentStep.event_id == event_id, AgentStep.agent.in_(["scout", "change_detection"])
                        ),
                    )
                    .order_by(AgentStep.started_at)
                )
            ).scalars()
        )
    return EventDetail(
        event=EventOut.model_validate(event).model_copy(
            update={"competitor_name": competitor.name if competitor else ""}
        ),
        competitor=CompetitorOut.model_validate(competitor),
        source=SourceOut.model_validate(source) if source else None,
        change=ChangeOut.model_validate(change) if change else None,
        evidence=[EvidenceOut.model_validate(e) for e in evidence],
        verification=VerificationOut.model_validate(verification) if verification else None,
        impact=ImpactOut.model_validate(impact) if impact else None,
        steps=[AgentStepOut.model_validate(s) for s in steps],
        priority_factors=event.priority_factors,
    )


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(event_id: uuid.UUID, body: EventUpdate, db: AsyncSession = Depends(get_db)):
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    event.status = body.status.value
    await db.commit()
    await db.refresh(event)
    return EventOut.model_validate(event)
