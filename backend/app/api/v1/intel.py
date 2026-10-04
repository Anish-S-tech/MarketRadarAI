"""Briefs, knowledge search, agent runs, realtime stream and LLM status."""

import asyncio
import json
import uuid
from datetime import date

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.brief_graph import generate_daily_brief
from app.alerts.delivery import user_channel
from app.config import settings
from app.db.enums import Role, RunStatus
from app.db.models import AgentRun, AgentStep, Brief, Source
from app.deps import Principal, get_db, get_principal, require_admin, require_roles
from app.knowledge.retrieval import hybrid_search
from app.schemas.dto import (
    AgentRunDetail,
    AgentRunOut,
    AgentStepOut,
    BriefGenerateIn,
    BriefMeta,
    BriefOut,
    CheckQueued,
    KnowledgeHit,
    LLMStatus,
    Page,
)

router = APIRouter(tags=["intelligence"])


# ---------------- briefs ----------------
@router.get("/briefs", response_model=list[BriefMeta])
async def list_briefs(
    role: str | None = None,
    limit: int = Query(30, le=200),
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Brief).order_by(Brief.brief_date.desc(), Brief.role).limit(limit)
    if role:
        stmt = stmt.where(Brief.role == role)
    return list((await db.execute(stmt)).scalars())


@router.get("/briefs/latest", response_model=BriefOut | None)
async def latest_brief(p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    role = p.role.value if p.role != Role.admin else "general"
    for r in (role, "general"):
        b = (
            await db.execute(select(Brief).where(Brief.role == r).order_by(Brief.brief_date.desc()).limit(1))
        ).scalar_one_or_none()
        if b:
            return b
    return None


@router.get("/briefs/{brief_id}", response_model=BriefOut)
async def get_brief(brief_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    b = await db.get(Brief, brief_id)
    if not b:
        raise HTTPException(404, "Brief not found")
    return b


@router.post("/briefs/generate", dependencies=[Depends(require_roles(Role.executive))])
async def generate_brief(body: BriefGenerateIn, p: Principal = Depends(get_principal)) -> dict:
    d = body.brief_date or date.today()
    if body.sync:
        return await generate_daily_brief(
            p.org_id, d, deliver=body.deliver, trigger="manual", window_hours=body.window_hours
        )
    from app.workers.tasks import generate_brief as task

    task.delay(str(p.org_id), d.isoformat(), "manual")
    return {"queued": True}


# ---------------- knowledge ----------------
@router.get("/knowledge/search", response_model=list[KnowledgeHit])
async def knowledge_search(
    q: str = Query(..., min_length=2),
    competitor_id: uuid.UUID | None = None,
    kind: list[str] | None = Query(None),
    limit: int = Query(15, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await hybrid_search(db, q, competitor_id=competitor_id, kinds=kind, limit=limit)


# ---------------- agent runs ----------------
@router.get("/agent-runs", response_model=Page[AgentRunOut])
async def list_runs(
    status: str | None = None,
    graph: str | None = None,
    source_id: uuid.UUID | None = None,
    hide_skipped: bool = True,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func

    stmt = select(AgentRun, Source.name).outerjoin(Source, Source.id == AgentRun.source_id)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    elif hide_skipped:
        stmt = stmt.where(AgentRun.status != RunStatus.skipped.value)
    if graph:
        stmt = stmt.where(AgentRun.graph == graph)
    if source_id:
        stmt = stmt.where(AgentRun.source_id == source_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AgentRun.started_at.desc()).limit(limit).offset(offset))).all()
    items = [AgentRunOut.model_validate(r).model_copy(update={"source_name": n}) for r, n in rows]
    return Page[AgentRunOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail)
async def get_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    steps = list(
        (
            await db.execute(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.started_at)
            )
        ).scalars()
    )
    src = await db.get(Source, run.source_id) if run.source_id else None
    return AgentRunDetail(
        **AgentRunOut.model_validate(run).model_dump(exclude={"source_name"}),
        source_name=src.name if src else None,
        steps=[AgentStepOut.model_validate(s) for s in steps],
    )


@router.post("/agent-runs/{run_id}/retry", response_model=CheckQueued, dependencies=[Depends(require_admin)])
async def retry_run(
    run_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
):
    """Re-enqueue a failed/dead-lettered run under the same idempotency key -> resumes from its checkpoint."""
    from app.workers.tasks import check_source

    run = await db.get(AgentRun, run_id)
    if not run or run.graph != "intel_pipeline" or not run.source_id:
        raise HTTPException(404, "Run not found")
    if run.status not in (RunStatus.failed.value, RunStatus.dead_letter.value):
        raise HTTPException(409, f"Run is {run.status}; only failed runs can be retried")
    run.status = RunStatus.failed.value
    await db.commit()
    check_source.apply_async(args=[str(p.org_id), str(run.source_id), run.idempotency_key, "retry"])
    return CheckQueued(queued=True, idempotency_key=run.idempotency_key)


# ---------------- realtime ----------------
@router.get("/stream")
async def stream(request: Request, p: Principal = Depends(get_principal)):
    """Server-sent events for in-app alerts (EventSource passes the token as ?token=)."""
    if p.user_id is None:
        raise HTTPException(403, "User context required")
    channel = user_channel(p.user_id)

    async def gen():
        r = aioredis.from_url(settings.redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield {"event": "ready", "data": "{}"}
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg and msg.get("type") == "message":
                    data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                    yield {"event": json.loads(data).get("type", "message"), "data": data}
                else:
                    yield {"event": "ping", "data": "{}"}
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            await r.aclose()

    return EventSourceResponse(gen())


# ---------------- LLM status ----------------
@router.get("/system/llm", response_model=LLMStatus)
async def llm_status(_: Principal = Depends(get_principal)):
    wanted = {settings.llm_model_classify, settings.llm_model_reason, settings.embed_model}
    available: list[str] = []
    reachable = False
    if settings.llm_provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{settings.ollama_url.rstrip('/')}/api/tags")
                r.raise_for_status()
                available = [m["name"] for m in r.json().get("models", [])]
                reachable = True
        except (httpx.HTTPError, ValueError):
            pass

    def present(name: str) -> bool:
        return name in available or f"{name}:latest" in available

    return LLMStatus(
        provider=settings.llm_provider,
        host=settings.ollama_url,
        reachable=reachable,
        classify_model=settings.llm_model_classify,
        reason_model=settings.llm_model_reason,
        embed_model=settings.embed_model,
        available_models=available,
        missing_models=sorted(m for m in wanted if reachable and not present(m)),
    )
