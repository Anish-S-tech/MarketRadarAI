"""Per-agent-step audit trail (agent_steps table), Prometheus timings and OTel spans."""

import functools
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger
from app.core.telemetry import NODE_LATENCY, span
from app.db.base import utcnow
from app.db.enums import RunStatus
from app.db.models import AgentStep
from app.db.session import tenant_session
from app.llm.client import llm_calls

log = get_logger(__name__)

NodeFn = Callable[[Any], Awaitable[dict[str, Any]]]


def _brief(state: dict[str, Any]) -> dict[str, Any]:
    keep = ("source_id", "change_id", "event_id", "snapshot_id", "scout_status")
    return {k: state[k] for k in keep if state.get(k)}


def traced(agent: str) -> Callable[[NodeFn], NodeFn]:
    """Wraps a LangGraph node. Nodes may return a `_summary` dict (popped before the state update)."""

    def deco(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: Any) -> dict[str, Any]:
            org_id = uuid.UUID(state["org_id"])
            run_id = uuid.UUID(state["run_id"])
            calls: list[dict[str, Any]] = []
            token = llm_calls.set(calls)
            started = utcnow()
            t0 = time.perf_counter()
            status, error, update = RunStatus.succeeded, None, {}
            try:
                with span(f"agent.{agent}", run_id=str(run_id), event_id=state.get("event_id")):
                    update = await fn(state) or {}
                return {k: v for k, v in update.items() if k != "_summary"}
            except Exception as e:
                status, error = RunStatus.failed, f"{type(e).__name__}: {e}"
                log.exception("agent.step_failed", agent=agent, run_id=str(run_id))
                raise
            finally:
                llm_calls.reset(token)
                latency = time.perf_counter() - t0
                NODE_LATENCY.labels(agent, status.value).observe(latency)
                event_id = update.get("event_id") or state.get("event_id")
                try:
                    async with tenant_session(org_id) as db:
                        db.add(
                            AgentStep(
                                org_id=org_id,
                                run_id=run_id,
                                agent=agent,
                                status=status.value,
                                event_id=uuid.UUID(event_id) if event_id else None,
                                started_at=started,
                                finished_at=utcnow(),
                                latency_ms=int(latency * 1000),
                                models=calls,
                                input_summary=_brief(state),
                                output_summary=update.get("_summary", {}),
                                error=error,
                            )
                        )
                        await db.commit()
                except Exception:
                    log.exception("agent.trace_write_failed", agent=agent)

        return wrapper

    return deco
