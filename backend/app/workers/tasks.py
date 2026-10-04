import asyncio
import random
import uuid
from datetime import date, timedelta

from celery import Task
from sqlalchemy import select, update

from app.agents.brief_graph import brief_due, generate_daily_brief
from app.agents.runner import mark_dead_letter, run_intel_pipeline
from app.config import settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import Brief, KBChunk, Organization, Source
from app.db.session import system_session
from app.llm.client import get_llm
from app.workers.celery_app import celery_app

log = get_logger(__name__)


class PipelineTask(Task):
    autoretry_for = (Exception,)
    retry_backoff = 30
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 3

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: ARG002
        # Retries exhausted -> dead letter (visible in the Agent Runs UI for manual replay).
        org_id, _source_id, key = args[0], args[1], args[2]
        asyncio.run(mark_dead_letter(uuid.UUID(org_id), key, f"{type(exc).__name__}: {exc}"))


@celery_app.task(base=PipelineTask, bind=True, name="app.workers.tasks.check_source")
def check_source(self, org_id: str, source_id: str, idempotency_key: str, trigger: str = "schedule") -> dict:
    log.info("task.check_source", source_id=source_id, attempt=self.request.retries)
    return asyncio.run(
        run_intel_pipeline(
            uuid.UUID(org_id), uuid.UUID(source_id), trigger=trigger, idempotency_key=idempotency_key
        )
    )


async def _dispatch_due(limit: int = 200) -> int:
    now = utcnow()
    async with system_session() as db:
        rows = (
            (
                await db.execute(
                    select(Source)
                    .where(Source.is_active.is_(True), Source.next_check_at <= now)
                    .order_by(Source.next_check_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        jobs = []
        for s in rows:
            slot = s.next_check_at.strftime("%Y%m%dT%H%M")
            # Lease: push next_check_at forward so the next beat tick doesn't re-dispatch while it runs.
            s.next_check_at = now + timedelta(minutes=max(15, s.check_interval_minutes))
            jobs.append((str(s.org_id), str(s.id), f"intel:{s.id}:{slot}"))
        await db.commit()
    for org_id, source_id, key in jobs:
        check_source.apply_async(
            args=[org_id, source_id, key, "schedule"],
            countdown=random.randint(0, settings.scheduler_jitter_seconds),
        )
    return len(jobs)


@celery_app.task(name="app.workers.tasks.dispatch_due_sources")
def dispatch_due_sources() -> int:
    n = asyncio.run(_dispatch_due())
    if n:
        log.info("scheduler.dispatched", sources=n)
    return n


def enqueue_source_check(org_id: uuid.UUID, source_id: uuid.UUID, trigger: str = "manual") -> str:
    key = f"intel:{source_id}:{trigger}:{uuid.uuid4().hex[:12]}"
    check_source.apply_async(args=[str(org_id), str(source_id), key, trigger])
    return key


async def _dispatch_briefs() -> int:
    now = utcnow()
    today = now.date()
    async with system_session() as db:
        orgs = list((await db.execute(select(Organization))).scalars())
        done = set(
            (
                await db.execute(
                    select(Brief.org_id).where(Brief.brief_date == today, Brief.role == "general")
                )
            ).scalars()
        )
    n = 0
    for org in orgs:
        if brief_due(org, now, org.id in done):
            generate_brief.delay(str(org.id), today.isoformat())
            n += 1
    return n


@celery_app.task(name="app.workers.tasks.dispatch_daily_briefs")
def dispatch_daily_briefs() -> int:
    return asyncio.run(_dispatch_briefs())


@celery_app.task(
    name="app.workers.tasks.generate_brief", autoretry_for=(Exception,), retry_backoff=60, max_retries=2
)
def generate_brief(org_id: str, brief_date: str, trigger: str = "schedule") -> dict:
    return asyncio.run(
        generate_daily_brief(uuid.UUID(org_id), date.fromisoformat(brief_date), trigger=trigger)
    )


async def _reindex(batch: int = 64) -> int:
    llm = get_llm()
    async with system_session() as db:
        rows = list(
            (
                await db.execute(
                    select(KBChunk.id, KBChunk.title, KBChunk.content)
                    .where(KBChunk.embedding.is_(None))
                    .limit(batch)
                )
            ).all()
        )
        if not rows:
            return 0
        vectors = await llm.embed([f"{r.title}\n{r.content}" for r in rows])
        if not vectors:
            return 0
        for r, v in zip(rows, vectors, strict=True):
            await db.execute(update(KBChunk).where(KBChunk.id == r.id).values(embedding=v))
        await db.commit()
        return len(rows)


@celery_app.task(name="app.workers.tasks.reindex_embeddings")
def reindex_embeddings() -> int:
    return asyncio.run(_reindex())
