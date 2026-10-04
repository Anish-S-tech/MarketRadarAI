"""Prioritisation: deterministic, explainable Low/Medium/High/Critical scoring."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.agents.scoring import prioritize
from app.agents.tracing import traced
from app.core.telemetry import EVENTS_CREATED
from app.db.base import utcnow
from app.db.models import Event, ImpactAssessment
from app.db.session import tenant_session

NOVELTY_WINDOW = timedelta(days=30)


@traced("prioritize")
async def prioritize_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    event_id = uuid.UUID(state["event_id"])
    impact = state.get("impact") or {}

    async with tenant_session(org_id) as db:
        event = await db.get(Event, event_id)
        assert event is not None
        similar = (
            await db.execute(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.competitor_id == event.competitor_id,
                    Event.category == event.category,
                    Event.id != event.id,
                    Event.detected_at >= utcnow() - NOVELTY_WINDOW,
                )
            )
        ).scalar_one()
        novelty = 1.0 if similar == 0 else 0.6 if similar == 1 else 0.3

        result = prioritize(
            max_severity=int(impact.get("max_severity", 2)),
            threat_tier=int(impact.get("threat_tier", 3)),
            category=event.category,
            confidence=event.confidence_score or 0.0,
            confidence_level=event.confidence_level or "unverified",
            novelty=novelty,
        )
        event.priority = result.priority.value
        event.priority_score = result.score
        event.priority_factors = {**result.factors, "similar_recent_events": similar}
        event.stage = "alerting"
        ia = (
            await db.execute(select(ImpactAssessment).where(ImpactAssessment.event_id == event.id))
        ).scalar_one_or_none()
        if ia:
            ia.priority_rationale = result.explanation
        await db.commit()
        EVENTS_CREATED.labels(result.priority.value, event.category).inc()

    return {
        "priority": {"priority": result.priority.value, "score": result.score},
        "_summary": {
            "priority": result.priority.value,
            "score": result.score,
            "explanation": result.explanation,
        },
    }
