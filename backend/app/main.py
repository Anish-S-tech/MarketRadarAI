from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1 import admin, alerts, auth, company, competitors, events, intel, sources
from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import limiter
from app.core.telemetry import configure_tracing
from app.db import session as db_session
from app.monitoring.netsafety import UnsafeURLError

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    configure_tracing("marketradar-api")
    if settings.env == "prod" and settings.jwt_secret.startswith(("change-me", "dev-only")):
        raise RuntimeError("JWT_SECRET must be set in production")
    log.info("api.startup", env=settings.env, llm_provider=settings.llm_provider)
    yield
    await db_session.engine.dispose()


app = FastAPI(
    title="MarketRadarAI API",
    version="0.1.0",
    description="Agentic competitive intelligence platform",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    SessionMiddleware, secret_key=settings.session_secret, https_only=settings.env == "prod", same_site="lax"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.url.path.startswith("/api/docs"):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.env == "prod":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(UnsafeURLError)
async def unsafe_url_handler(_: Request, exc: UnsafeURLError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


api = APIRouter(prefix="/api/v1")
for r in (
    auth.router,
    admin.router,
    company.router,
    competitors.router,
    competitors.graph_router,
    sources.router,
    sources.snap_router,
    events.router,
    alerts.router,
    intel.router,
):
    api.include_router(r)
app.include_router(api)


@app.get("/healthz", include_in_schema=False)
@limiter.exempt
async def healthz():
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
@limiter.exempt
async def readyz():
    checks = {}
    try:
        async with db_session.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", **checks}
    )


@app.get("/metrics", include_in_schema=False)
@limiter.exempt
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
except Exception:  # pragma: no cover
    pass
