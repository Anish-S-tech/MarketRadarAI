"""Organisation, users and API keys (admin)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, new_api_key
from app.db.models import ApiKey, Organization, User
from app.db.session import system_session
from app.deps import Principal, get_db, get_principal, require_admin
from app.schemas.dto import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    OrgOut,
    OrgUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(tags=["admin"])


@router.get("/org", response_model=OrgOut)
async def get_org(p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    return await db.get(Organization, p.org_id)


@router.patch("/org", response_model=OrgOut, dependencies=[Depends(require_admin)])
async def update_org(
    body: OrgUpdate, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    org = await db.get(Organization, p.org_id)
    assert org is not None
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(org, k, v)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)):
    return list((await db.execute(select(User).order_by(User.created_at))).scalars())


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_user(
    body: UserCreate, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    async with system_session() as sdb:  # email uniqueness is global across tenants
        if (await sdb.execute(select(User.id).where(User.email == body.email.lower()))).scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        org_id=p.org_id,
        email=body.email.lower(),
        full_name=body.full_name,
        role=body.role.value,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_admin)])
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    data = body.model_dump(exclude_unset=True)
    if user.id == p.user_id and (
        data.get("is_active") is False or ("role" in data and data["role"] != user.role)
    ):
        raise HTTPException(400, "You cannot deactivate or demote yourself")
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    for k, v in data.items():
        setattr(user, k, v.value if hasattr(v, "value") else v)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_user(
    user_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    if user_id == p.user_id:
        raise HTTPException(400, "You cannot delete yourself")
    user = await db.get(User, user_id)
    if user:
        await db.delete(user)
        await db.commit()


@router.get("/api-keys", response_model=list[ApiKeyOut], dependencies=[Depends(require_admin)])
async def list_keys(db: AsyncSession = Depends(get_db)):
    return list((await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars())


@router.post(
    "/api-keys", response_model=ApiKeyCreated, status_code=201, dependencies=[Depends(require_admin)]
)
async def create_key(
    body: ApiKeyCreate, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    key, prefix, key_hash = new_api_key()
    row = ApiKey(org_id=p.org_id, name=body.name, prefix=prefix, key_hash=key_hash, role=body.role.value)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ApiKeyCreated(**ApiKeyOut.model_validate(row).model_dump(), key=key)


@router.delete("/api-keys/{key_id}", status_code=204, dependencies=[Depends(require_admin)])
async def revoke_key(key_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(ApiKey, key_id)
    if row and not row.revoked_at:
        row.revoked_at = datetime.now(UTC)
        await db.commit()
