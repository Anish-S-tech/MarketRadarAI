"""FastAPI dependencies: authentication, RBAC and tenant-scoped DB sessions."""

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token, sha256
from app.db.enums import Role
from app.db.models import ApiKey, User
from app.db.session import system_session, tenant_session

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID | None
    org_id: uuid.UUID
    role: Role
    via_api_key: bool = False


async def _principal_from_api_key(key: str) -> Principal | None:
    async with system_session() as s:
        row = (
            await s.execute(select(ApiKey).where(ApiKey.key_hash == sha256(key), ApiKey.revoked_at.is_(None)))
        ).scalar_one_or_none()
        if not row:
            return None
        row.last_used_at = datetime.now(UTC)
        await s.commit()
        return Principal(user_id=None, org_id=row.org_id, role=Role(row.role), via_api_key=True)


async def get_principal(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> Principal:
    token = creds.credentials if creds else request.query_params.get("token")  # SSE can't set headers
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if token.startswith("mr_"):
        p = await _principal_from_api_key(token)
        if not p:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        request.state.principal = p
        return p
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from e
    p = Principal(
        user_id=uuid.UUID(payload["sub"]), org_id=uuid.UUID(payload["org"]), role=Role(payload["role"])
    )
    request.state.principal = p
    return p


async def get_db(principal: Principal = Depends(get_principal)) -> AsyncIterator[AsyncSession]:
    async with tenant_session(principal.org_id) as s:
        yield s


async def get_current_user(
    principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
) -> User:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User context required")
    user = await db.get(User, principal.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return user


def require_roles(*roles: Role) -> Callable:
    allowed = set(roles) | {Role.admin}

    async def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return principal

    return dep


require_admin = require_roles(Role.admin)
