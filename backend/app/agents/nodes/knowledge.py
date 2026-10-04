"""Knowledge step: folds a verified event into persistent competitive memory (pricing history, products,
features, relationships, semantic chunks, rolling competitor profile)."""

import uuid
from typing import Any

from sqlalchemy import select

from app.agents.tracing import traced
from app.db.enums import ConfidenceLevel
from app.db.models import Change, Competitor, Event, Evidence, Snapshot
from app.db.session import tenant_session
from app.knowledge import kb_service
from app.llm.client import get_llm
from app.llm.schemas import CompetitorSummary, EntityExtraction

ENTITY_CATEGORIES = {"product", "feature", "partnership", "strategy", "financial", "positioning"}


@traced("knowledge")
async def knowledge_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    event_id = uuid.UUID(state["event_id"])
    llm = get_llm()
    summary: dict[str, Any] = {}

    async with tenant_session(org_id) as db:
        event = await db.get(Event, event_id)
        assert event is not None
        change = await db.get(Change, event.change_id) if event.change_id else None
        competitor = await db.get(Competitor, event.competitor_id)
        assert competitor is not None
        disputed = event.confidence_level == ConfidenceLevel.disputed

        # Pricing history (only from directly observed, non-disputed pricing tables).
        if change and change.kind == "pricing" and not disputed:
            snap = await db.get(Snapshot, change.snapshot_id)
            plans = (snap.structured.get("pricing") or {}).get("plans", []) if snap else []
            if plans:
                summary["price_points"] = await kb_service.sync_price_points(
                    db,
                    org_id,
                    competitor.id,
                    plans,
                    event_id=event.id,
                    snapshot_id=snap.id,  # type: ignore[union-attr]
                    observed_at=snap.fetched_at,  # type: ignore[union-attr]
                )

        # Products / features / relationships.
        if event.category in ENTITY_CATEGORIES and not disputed:
            text_parts = [event.title, event.summary, *event.key_facts]
            if change:
                text_parts += change.diff.get("added", [])[:40]
                item = change.diff.get("item") or {}
                text_parts += [item.get("title", ""), item.get("summary", "")]
            ents = await llm.complete(
                "extract_entities",
                EntityExtraction,
                {"competitor": competitor.name, "text": "\n".join(p for p in text_parts if p)},
                tier="classify",
            )
            summary["products_added"] = await kb_service.upsert_products(
                db, org_id, competitor.id, ents.products, event.id
            )
            summary["relationships_added"] = await kb_service.upsert_relationships(
                db, org_id, competitor.id, ents.relationships, event.id
            )

        # Semantic memory.
        supporting = list(
            (
                await db.execute(
                    select(Evidence)
                    .where(Evidence.event_id == event.id)
                    .order_by(Evidence.reliability_tier)
                    .limit(4)
                )
            ).scalars()
        )
        chunks = [
            {
                "kind": "event",
                "ref_id": event.id,
                "competitor_id": competitor.id,
                "title": event.title,
                "content": f"{event.summary}\nFacts: {'; '.join(event.key_facts)}\nConfidence: {event.confidence_level}",
                "meta": {"category": event.category, "confidence": event.confidence_level},
                "occurred_at": event.detected_at,
            }
        ]
        chunks += [
            {
                "kind": "evidence",
                "ref_id": ev.id,
                "competitor_id": competitor.id,
                "title": ev.title,
                "content": ev.snippet[:3000],
                "meta": {"url": ev.url, "event_id": str(event.id), "tier": ev.reliability_tier},
            }
            for ev in supporting
            if any(s.get("stance") == "supports" for s in ev.stances)
        ]
        summary["chunks"] = len(await kb_service.add_chunks(db, org_id, chunks))

        # Rolling competitor profile.
        history = await kb_service.recent_history(db, competitor.id, limit=8)
        prof = await llm.complete(
            "competitor_summary",
            CompetitorSummary,
            {
                "competitor": competitor.name,
                "description": competitor.description,
                "current_summary": competitor.summary,
                "recent_events": [{"title": e.title, "category": e.category} for e in history],
            },
            tier="classify",
        )
        competitor.summary = prof.summary[:4000]
        await db.commit()

    return {"_summary": summary}
