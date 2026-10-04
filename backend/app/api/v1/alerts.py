import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.enums import Role
from app.db.models import Alert, AlertSubscription, User
from app.deps import Principal, get_current_user, get_db, get_principal
from app.schemas.dto import AlertOut, Page, SubscriptionIn, SubscriptionOut

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=Page[AlertOut])
async def list_alerts(
    unread_only: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Alert).where(Alert.user_id == user.id, Alert.channel == "in_app")
    if unread_only:
        stmt = stmt.where(Alert.read_at.is_(None))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (await db.execute(stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset))).scalars()
    )
    return Page[AlertOut](
        items=[AlertOut.model_validate(a) for a in rows], total=total, limit=limit, offset=offset
    )


@router.get("/alerts/unread-count")
async def unread_count(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    n = (
        await db.execute(
            select(func.count())
            .select_from(Alert)
            .where(Alert.user_id == user.id, Alert.channel == "in_app", Alert.read_at.is_(None))
        )
    ).scalar_one()
    return {"unread": n}


@router.post("/alerts/{alert_id}/read", status_code=204)
async def mark_read(
    alert_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    a = await db.get(Alert, alert_id)
    if not a or a.user_id != user.id:
        raise HTTPException(404, "Alert not found")
    a.read_at = a.read_at or utcnow()
    await db.commit()


@router.post("/alerts/read-all", status_code=204)
async def mark_all_read(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(Alert).where(Alert.user_id == user.id, Alert.read_at.is_(None)).values(read_at=utcnow())
    )
    await db.commit()


# ---------------- subscriptions ----------------
def _can_edit(sub: AlertSubscription, p: Principal) -> bool:
    return p.role == Role.admin or (sub.user_id is not None and sub.user_id == p.user_id)


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    stmt = select(AlertSubscription).order_by(AlertSubscription.created_at)
    if p.role != Role.admin:
        stmt = stmt.where(or_(AlertSubscription.user_id == p.user_id, AlertSubscription.role == p.role.value))
    return list((await db.execute(stmt)).scalars())


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
async def create_subscription(
    body: SubscriptionIn, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    personal = body.personal or p.role != Role.admin
    if not personal and body.role is None:
        raise HTTPException(422, "Role-wide subscriptions need a role")
    sub = AlertSubscription(
        org_id=p.org_id,
        user_id=p.user_id if personal else None,
        role=None if personal else body.role.value,  # type: ignore[union-attr]
        name=body.name,
        categories=[c.value for c in body.categories],
        competitor_ids=[str(c) for c in body.competitor_ids],
        min_priority=body.min_priority.value,
        channels=body.channels,
        include_in_brief=body.include_in_brief,
        is_active=body.is_active,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


@router.put("/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def update_subscription(
    sub_id: uuid.UUID,
    body: SubscriptionIn,
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    sub = await db.get(AlertSubscription, sub_id)
    if not sub or not _can_edit(sub, p):
        raise HTTPException(404, "Subscription not found")
    sub.name = body.name
    if sub.user_id is None and body.role:
        sub.role = body.role.value
    sub.categories = [c.value for c in body.categories]
    sub.competitor_ids = [str(c) for c in body.competitor_ids]
    sub.min_priority = body.min_priority.value
    sub.channels = body.channels
    sub.include_in_brief = body.include_in_brief
    sub.is_active = body.is_active
    await db.commit()
    await db.refresh(sub)
    return sub


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(
    sub_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    sub = await db.get(AlertSubscription, sub_id)
    if not sub or not _can_edit(sub, p):
        raise HTTPException(404, "Subscription not found")
    await db.delete(sub)
    await db.commit()
