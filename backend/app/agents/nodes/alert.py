"""Alert Agent node: dispatches role-specific alerts for a prioritised event."""

import uuid
from typing import Any

from app.agents.tracing import traced
from app.alerts.router import dispatch_event_alerts
from app.db.models import Event
from app.db.session import tenant_session


@traced("alert")
async def alert_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    event_id = uuid.UUID(state["event_id"])
    async with tenant_session(org_id) as db:
        counts = await dispatch_event_alerts(db, event_id)
        event = await db.get(Event, event_id)
        assert event is not None
        event.stage = "complete"
        await db.commit()
        out = {
            "event_id": str(event.id),
            "title": event.title,
            "priority": event.priority,
            "category": event.category,
            "confidence": event.confidence_level,
        }
    return {"events": [out], "_summary": counts}
