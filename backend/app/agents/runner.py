"""Runs graphs with durable checkpoints, idempotency and an audit record (agent_runs)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.graph import build_intel_graph, checkpointer
from app.core.logging import get_logger
from app.core.telemetry import PIPELINE_OUTCOMES
from app.db.base import utcnow
from app.db.enums import RunStatus
from app.db.models import AgentRun
from app.db.session import tenant_session

log = get_logger(__name__)


async def _claim_run(
    org_id: uuid.UUID, graph: str, key: str, trigger: str, source_id: uuid.UUID | None
) -> tuple[AgentRun, bool]:
    """Create the run or return the existing one for this idempotency key. Returns (run, is_new)."""
    async with tenant_session(org_id) as db:
        existing = (
            await db.execute(select(AgentRun).where(AgentRun.idempotency_key == key))
        ).scalar_one_or_none()
        if existing:
            if existing.status in (RunStatus.failed, RunStatus.running):
                existing.attempts += 1
                existing.status = RunStatus.running.value
                existing.error = None
                await db.commit()
            return existing, False
        run_id = uuid.uuid4()
        run = AgentRun(
            id=run_id,
            org_id=org_id,
            graph=graph,
            source_id=source_id,
            trigger=trigger,
            idempotency_key=key,
            thread_id=f"{graph}:{run_id}",
            status=RunStatus.running.value,
        )
        db.add(run)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = (
                await db.execute(select(AgentRun).where(AgentRun.idempotency_key == key))
            ).scalar_one()
            return existing, False
        return run, True


async def _finish_run(
    org_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    status: RunStatus,
    outcome: str | None = None,
    error: str | None = None,
    summary: dict | None = None,
) -> None:
    async with tenant_session(org_id) as db:
        run = await db.get(AgentRun, run_id)
        if run is None:
            return
        run.status = status.value
        run.outcome = outcome
        run.error = error
        if summary is not None:
            run.summary = summary
        run.finished_at = utcnow()
        await db.commit()


async def mark_dead_letter(org_id: uuid.UUID, idempotency_key: str, error: str) -> None:
    async with tenant_session(org_id) as db:
        run = (
            await db.execute(select(AgentRun).where(AgentRun.idempotency_key == idempotency_key))
        ).scalar_one_or_none()
        if run:
            run.status = RunStatus.dead_letter.value
            run.error = error[:4000]
            run.finished_at = utcnow()
            await db.commit()


async def run_intel_pipeline(
    org_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    trigger: str = "schedule",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    key = idempotency_key or f"intel:{source_id}:{uuid.uuid4()}"
    run, is_new = await _claim_run(org_id, "intel_pipeline", key, trigger, source_id)
    if run.status in (RunStatus.succeeded, RunStatus.skipped, RunStatus.dead_letter):
        return {"run_id": str(run.id), "status": run.status, "idempotent_replay": True, **(run.summary or {})}

    config = {"configurable": {"thread_id": run.thread_id}, "recursion_limit": 60}
    initial = {
        "org_id": str(org_id),
        "source_id": str(source_id),
        "run_id": str(run.id),
        "trigger": trigger,
        "events": [],
        "duplicates": [],
        "errors": [],
    }
    try:
        async with checkpointer() as cp:
            graph = build_intel_graph().compile(checkpointer=cp)
            state = await graph.aget_state(config)
            if not is_new and state.next:
                log.info("pipeline.resume", run_id=str(run.id), next=list(state.next))
                result = await graph.ainvoke(None, config)
            elif not is_new and state.values and not state.next:
                result = state.values
            else:
                result = await graph.ainvoke(initial, config)
    except Exception as e:
        PIPELINE_OUTCOMES.labels("failed").inc()
        await _finish_run(org_id, run.id, status=RunStatus.failed, error=f"{type(e).__name__}: {e}"[:4000])
        raise

    scout_status = result.get("scout_status", "unknown")
    events = result.get("events", [])
    errors = result.get("errors", [])
    if scout_status == "error":
        status, outcome = RunStatus.failed, "fetch_error"
    elif events:
        status, outcome = RunStatus.succeeded, f"{len(events)}_events"
    elif result.get("duplicates"):
        status, outcome = RunStatus.succeeded, "corroborated_existing_event"
    elif scout_status in ("unchanged", "not_modified"):
        status, outcome = RunStatus.skipped, scout_status
    else:
        status, outcome = (
            RunStatus.succeeded,
            "no_significant_change" if scout_status == "changed" else scout_status,
        )
    summary = {
        "scout_status": scout_status,
        "changes": result.get("changes", []),
        "events": events,
        "duplicates": result.get("duplicates", []),
        "errors": errors,
    }
    await _finish_run(
        org_id,
        run.id,
        status=status,
        outcome=outcome,
        error="; ".join(errors)[:4000] or None,
        summary=summary,
    )
    PIPELINE_OUTCOMES.labels("events" if outcome.endswith("_events") else outcome).inc()
    return {"run_id": str(run.id), "status": status.value, "outcome": outcome, **summary}
