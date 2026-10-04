"""Impact Analysis Agent: evaluates what the competitor move means for OUR products, customers,
pricing and competitive position, with role-specific implications and recommended actions."""

import uuid
from typing import Any

from sqlalchemy import select

from app.agents.tracing import traced
from app.db.models import (
    Change,
    CompanyProfile,
    Competitor,
    CustomerSegment,
    Event,
    ImpactAssessment,
    OwnPricePoint,
    OwnProduct,
)
from app.db.session import tenant_session
from app.knowledge import kb_service
from app.llm.client import get_llm
from app.llm.schemas import ImpactAnalysis


@traced("impact")
async def impact_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    event_id = uuid.UUID(state["event_id"])
    conf = state.get("confidence") or {}

    async with tenant_session(org_id) as db:
        event = await db.get(Event, event_id)
        assert event is not None
        competitor = await db.get(Competitor, event.competitor_id)
        assert competitor is not None
        change = await db.get(Change, event.change_id) if event.change_id else None
        company = (await db.execute(select(CompanyProfile).limit(1))).scalar_one_or_none()
        products = list((await db.execute(select(OwnProduct))).scalars())
        prices = list((await db.execute(select(OwnPricePoint))).scalars())
        segments = list((await db.execute(select(CustomerSegment))).scalars())
        history = await kb_service.recent_history(db, competitor.id, limit=6, exclude_event_id=event.id)

        ctx = {
            "company": {
                "name": company.name if company else "Our company",
                "description": company.description if company else "",
                "positioning": company.positioning if company else "",
                "differentiators": company.differentiators if company else [],
            },
            "own_products": [
                {"name": p.name, "category": p.category, "description": p.description} for p in products
            ],
            "own_prices": [
                {
                    "plan": p.plan,
                    "price": float(p.price) if p.price is not None else None,
                    "currency": p.currency,
                    "period": p.period,
                }
                for p in prices
            ],
            "segments": [
                {"name": s.name, "description": s.description, "revenue_share": s.revenue_share}
                for s in segments
            ],
            "competitor": competitor.name,
            "threat_tier": competitor.threat_tier,
            "competitor_profile": competitor.summary or competitor.description,
            "recent_history": [f"{h.detected_at:%Y-%m-%d} {h.title}" for h in history]
            + [f"(memory) {k['title']}: {k['content'][:160]}" for k in (state.get("kb_context") or [])[:3]],
            "title": event.title,
            "summary": event.summary,
            "category": event.category,
            "significance": change.significance if change else 0.5,
            "key_facts": event.key_facts,
            "confidence_level": event.confidence_level or "unverified",
            "verified_claims": conf.get("verified_claims", []),
            "pricing_changes": (change.diff.get("pricing_changes", []) if change else []),
        }
        analysis = await get_llm().complete("impact", ImpactAnalysis, ctx)

        db.add(
            ImpactAssessment(
                org_id=org_id,
                event_id=event.id,
                summary=analysis.summary,
                overall_severity=analysis.max_severity,
                dimensions={
                    "products": analysis.products.model_dump(),
                    "customers": analysis.customers.model_dump(),
                    "pricing": analysis.pricing.model_dump(),
                    "competitive_position": analysis.competitive_position.model_dump(),
                },
                affected_products=analysis.affected_products,
                affected_segments=analysis.affected_segments,
                role_implications=analysis.role_implications.model_dump(),
                recommended_actions=[a.model_dump() for a in analysis.recommended_actions],
            )
        )
        event.stage = "prioritizing"
        await db.commit()

    return {
        "impact": {"max_severity": analysis.max_severity, "threat_tier": competitor.threat_tier},
        "_summary": {
            "max_severity": analysis.max_severity,
            "summary": analysis.summary[:500],
            "actions": len(analysis.recommended_actions),
        },
    }
