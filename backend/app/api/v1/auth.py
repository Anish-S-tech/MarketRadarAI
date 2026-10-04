import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    hash_password,
    new_opaque_token,
    sha256,
    verify_password,
)
from app.db.enums import BUSINESS_ROLES, Role
from app.db.models import AlertSubscription, CompanyProfile, Organization, RefreshToken, User
from app.db.session import system_session
from app.deps import get_current_user
from app.schemas.dto import AuthConfigOut, LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


async def issue_tokens(db, user: User) -> TokenOut:
    refresh = new_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=sha256(refresh),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return TokenOut(
        access_token=create_access_token(user.id, user.org_id, user.role),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserOut.model_validate(user),
    )


def default_subscriptions(org_id: uuid.UUID) -> list[AlertSubscription]:
    subs = [
        AlertSubscription(
            org_id=org_id,
            role=r.value,
            name=f"{r.value.title()} default",
            min_priority="medium",
            channels=["in_app", "email"],
        )
        for r in BUSINESS_ROLES
    ]
    subs.append(
        AlertSubscription(
            org_id=org_id,
            role=Role.admin.value,
            name="Admin default",
            min_priority="high",
            channels=["in_app", "email"],
        )
    )
    return subs


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    return AuthConfigOut(
        allow_signup=settings.allow_signup, oidc_enabled=settings.oidc_enabled, oidc_name=settings.oidc_name
    )


@router.post("/register", response_model=TokenOut, status_code=201)
@limiter.limit(settings.rate_limit_auth)
async def register(request: Request, body: RegisterIn) -> TokenOut:  # noqa: ARG001
    if not settings.allow_signup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Self-service signup is disabled")
    async with system_session() as db:
        if (await db.execute(select(User.id).where(User.email == body.email.lower()))).scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
        slug = re.sub(r"[^a-z0-9]+", "-", body.org_name.lower()).strip("-")[:80] or "org"
        if (await db.execute(select(Organization.id).where(Organization.slug == slug))).scalar_one_or_none():
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"
        org = Organization(name=body.org_name, slug=slug, settings={})
        db.add(org)
        await db.flush()
        user = User(
            org_id=org.id,
            email=body.email.lower(),
            full_name=body.full_name,
            hashed_password=hash_password(body.password),
            role=Role.admin.value,
        )
        db.add(user)
        db.add(CompanyProfile(org_id=org.id, name=body.org_name))
        db.add_all(default_subscriptions(org.id))
        await db.flush()
        return await issue_tokens(db, user)


@router.post("/login", response_model=TokenOut)
@limiter.limit(settings.rate_limit_auth)
async def login(request: Request, body: LoginIn) -> TokenOut:  # noqa: ARG001
    async with system_session() as db:
        user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
        if not user or not user.is_active or not verify_password(body.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
        return await issue_tokens(db, user)


@router.post("/refresh", response_model=TokenOut)
@limiter.limit("30/minute")
async def refresh(request: Request, body: RefreshIn) -> TokenOut:  # noqa: ARG001
    async with system_session() as db:
        rt = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token))
            )
        ).scalar_one_or_none()
        if not rt or rt.revoked_at or rt.expires_at < datetime.now(UTC):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
        user = await db.get(User, rt.user_id)
        if not user or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
        rt.revoked_at = datetime.now(UTC)  # rotation
        return await issue_tokens(db, user)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn) -> None:
    async with system_session() as db:
        rt = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token))
            )
        ).scalar_one_or_none()
        if rt and not rt.revoked_at:
            rt.revoked_at = datetime.now(UTC)
            await db.commit()


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


# ---------------- OIDC (optional; users must be pre-provisioned by an admin) ----------------
_oauth = None


def _oidc_client():
    global _oauth
    if not settings.oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OIDC not enabled")
    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth

        _oauth = OAuth()
        _oauth.register(
            name="sso",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_discovery_url,
            client_kwargs={"scope": "openid email profile"},
        )
    return _oauth.sso


@router.get("/oidc/login")
async def oidc_login(request: Request):
    client = _oidc_client()
    return await client.authorize_redirect(request, str(request.url_for("oidc_callback")))


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request):
    client = _oidc_client()
    token = await client.authorize_access_token(request)
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Verified email required")
    async with system_session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No MarketRadar account for this identity")
        user.oidc_sub = info.get("sub")
        tokens = await issue_tokens(db, user)
    fragment = urlencode({"access_token": tokens.access_token, "refresh_token": tokens.refresh_token})
    return RedirectResponse(f"{settings.frontend_url}/auth/callback#{fragment}")
