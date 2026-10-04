"""Async SQLAlchemy engine/session with Postgres row-level-security tenant context.

Every transaction starts by setting two transaction-local GUCs that the RLS policies read:
  app.org_id       -> the tenant the session is scoped to
  app.bypass_rls   -> 'on' for trusted system contexts (workers, login lookup, migrations/seed)
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import settings


def _make_engine(null_pool: bool = False):
    kwargs: dict = {"pool_pre_ping": True}
    if null_pool:
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_pool_size
    return create_async_engine(settings.database_url, **kwargs)


# Workers run each task in a fresh event loop -> NullPool avoids cross-loop connection reuse.
engine = _make_engine(null_pool=settings.env == "test")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

_worker_engine = None
_worker_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def use_worker_engine() -> None:
    """Switch the module-level session factory to a NullPool engine (Celery workers)."""
    global engine, SessionLocal, _worker_engine, _worker_sessionmaker
    if _worker_engine is None:
        _worker_engine = _make_engine(null_pool=True)
        _worker_sessionmaker = async_sessionmaker(_worker_engine, expire_on_commit=False, class_=AsyncSession)
    engine = _worker_engine
    SessionLocal = _worker_sessionmaker  # type: ignore[assignment]


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, transaction, connection) -> None:  # noqa: ARG001
    org_id = session.info.get("org_id")
    bypass = "on" if session.info.get("system") else "off"
    connection.execute(
        text("SELECT set_config('app.org_id', :org, true), set_config('app.bypass_rls', :bypass, true)"),
        {"org": str(org_id) if org_id else "", "bypass": bypass},
    )


@asynccontextmanager
async def tenant_session(org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    from app.db import session as mod  # resolve current factory (may be switched to worker engine)

    async with mod.SessionLocal() as s:
        s.info["org_id"] = org_id
        yield s


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    from app.db import session as mod

    async with mod.SessionLocal() as s:
        s.info["system"] = True
        yield s
