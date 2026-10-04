"""Our own company profile, products, pricing and segments (context for the Impact Agent)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Role
from app.db.models import CompanyProfile, CustomerSegment, OwnPricePoint, OwnProduct
from app.deps import Principal, get_db, get_principal, require_roles
from app.schemas.dto import (
    CompanyProfileIn,
    CompanyProfileOut,
    OwnPriceIn,
    OwnPriceOut,
    OwnProductIn,
    OwnProductOut,
    SegmentIn,
    SegmentOut,
)

router = APIRouter(prefix="/company", tags=["company"])
editor = Depends(require_roles(Role.executive, Role.product, Role.pricing, Role.marketing))


@router.get("", response_model=CompanyProfileOut | None)
async def get_profile(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(CompanyProfile).limit(1))).scalar_one_or_none()


@router.put("", response_model=CompanyProfileOut, dependencies=[editor])
async def put_profile(
    body: CompanyProfileIn, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    row = (await db.execute(select(CompanyProfile).limit(1))).scalar_one_or_none()
    if row is None:
        row = CompanyProfile(org_id=p.org_id, **body.model_dump())
        db.add(row)
    else:
        for k, v in body.model_dump().items():
            setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


def _crud(path: str, model, in_schema, out_schema):
    @router.get(f"/{path}", response_model=list[out_schema], name=f"list_{path}")
    async def list_items(db: AsyncSession = Depends(get_db)):
        return list((await db.execute(select(model).order_by(model.created_at))).scalars())

    @router.post(
        f"/{path}", response_model=out_schema, status_code=201, dependencies=[editor], name=f"create_{path}"
    )
    async def create_item(
        body: in_schema, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
    ):  # type: ignore[valid-type]
        row = model(org_id=p.org_id, **body.model_dump())
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @router.put(
        f"/{path}/{{item_id}}", response_model=out_schema, dependencies=[editor], name=f"update_{path}"
    )
    async def update_item(item_id: uuid.UUID, body: in_schema, db: AsyncSession = Depends(get_db)):  # type: ignore[valid-type]
        row = await db.get(model, item_id)
        if not row:
            raise HTTPException(404, "Not found")
        for k, v in body.model_dump().items():
            setattr(row, k, v)
        await db.commit()
        await db.refresh(row)
        return row

    @router.delete(f"/{path}/{{item_id}}", status_code=204, dependencies=[editor], name=f"delete_{path}")
    async def delete_item(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
        row = await db.get(model, item_id)
        if row:
            await db.delete(row)
            await db.commit()


_crud("products", OwnProduct, OwnProductIn, OwnProductOut)
_crud("prices", OwnPricePoint, OwnPriceIn, OwnPriceOut)
_crud("segments", CustomerSegment, SegmentIn, SegmentOut)
