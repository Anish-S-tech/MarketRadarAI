"""Integration fixtures: a real pgvector Postgres (testcontainers), migrated with the owner role, while the
application connects as a NON-superuser role so row-level security is actually enforced."""

import asyncio
import os
import shutil

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    return (
        shutil.which("docker") is not None
        and os.system("docker info >nul 2>&1" if os.name == "nt" else "docker info >/dev/null 2>&1") == 0
    )


@pytest.fixture(scope="session")
def pg_urls():
    if not _docker_available():
        pytest.skip("Docker is required for integration tests")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "pgvector/pgvector:pg16", username="owner", password="owner", dbname="mr", driver="asyncpg"
    ) as pg:
        owner = pg.get_connection_url()
        app_url = owner.replace("owner:owner@", "mr_app:mr_app@")
        yield owner, app_url


@pytest.fixture(scope="session")
async def database(pg_urls):
    owner_url, app_url = pg_urls
    from sqlalchemy import text

    engine = create_async_engine(owner_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE ROLE mr_app LOGIN PASSWORD 'mr_app'"))
        await conn.execute(text("GRANT USAGE ON SCHEMA public TO mr_app"))
    await engine.dispose()

    # Point the app at the test database *before* running migrations/grants.
    from app.config import settings

    settings.database_url = owner_url
    settings.migration_database_url = owner_url
    settings.use_postgres_checkpointer = True

    from alembic.config import Config

    from alembic import command

    here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    cfg.attributes["database_url"] = owner_url
    await asyncio.to_thread(command.upgrade, cfg, "head")

    from app.agents.graph import setup_checkpointer

    await setup_checkpointer()
    engine = create_async_engine(owner_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mr_app")
        )
        await conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mr_app"))
    await engine.dispose()

    # From here on the application runs as the RLS-constrained role.
    settings.database_url = app_url
    from app.db import session as db_session
    from app.db.session import _make_engine

    db_session.engine = _make_engine(null_pool=True)
    db_session.SessionLocal = async_sessionmaker(db_session.engine, expire_on_commit=False)

    from app.llm.client import HeuristicProvider, set_llm

    set_llm(HeuristicProvider())
    yield
    await db_session.engine.dispose()
