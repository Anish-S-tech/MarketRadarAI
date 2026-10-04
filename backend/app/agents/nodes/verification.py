"""Verification Agent: cross-checks every claim against every piece of evidence, attaches stances,
and computes an auditable confidence score/level."""

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.scoring import (
    ConfidenceResult,
    EvidenceItem,
    aggregate_confidence,
    grounded_stance,
    score_claim,
)
from app.agents.tracing import traced
from app.db.models import Competitor, Event, Evidence, Verification
from app.db.session import tenant_session
from app.llm.client import get_llm
from app.llm.schemas import EvidenceJudgment


def competitor_names(competitor: Competitor | None) -> list[str]:
    if competitor is None:
        return []
    return [competitor.name, *(competitor.aliases or []), competitor.domain.split(":")[0]]


def score_evidence(claims: list[str], evidence: list[Evidence]) -> ConfidenceResult:
    claim_scores = []
    for i, claim in enumerate(claims):
        items = [
            EvidenceItem(
                domain=ev.domain,
                tier=ev.reliability_tier,
                is_primary=ev.is_primary,
                stance=next((j["stance"] for j in ev.stances if j.get("claim_index") == i), "irrelevant"),
                published_at=ev.published_at,
            )
            for ev in evidence
        ]
        claim_scores.append(score_claim(claim, items))
    return aggregate_confidence(claim_scores)


def claims_payload(result: ConfidenceResult) -> list[dict[str, Any]]:
    return [
        {
            "claim": cs.claim,
            "score": cs.score,
            "supporting": cs.supporting,
            "contradicting": cs.contradicting,
            "independent_domains": cs.independent_domains,
            "has_primary": cs.has_primary,
        }
        for cs in result.claims
    ]


async def recompute_confidence(db: AsyncSession, event: Event) -> ConfidenceResult | None:
    """Re-score an existing event after new corroborating evidence was attached (e.g. a duplicate sighting)."""
    ver = (
        await db.execute(select(Verification).where(Verification.event_id == event.id))
    ).scalar_one_or_none()
    if ver is None:
        return None
    claims = [c["claim"] for c in ver.claims]
    evidence = list((await db.execute(select(Evidence).where(Evidence.event_id == event.id))).scalars())
    result = score_evidence(claims, evidence)
    ver.confidence_score, ver.level, ver.rationale = result.score, result.level.value, result.rationale
    ver.claims = claims_payload(result)
    event.confidence_score, event.confidence_level = result.score, result.level.value
    return result


@traced("verification")
async def verification_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    event_id = uuid.UUID(state["event_id"])
    claims: list[str] = state.get("claims") or []
    llm = get_llm()

    async with tenant_session(org_id) as db:
        event = await db.get(Event, event_id)
        assert event is not None
        competitor = await db.get(Competitor, event.competitor_id)
        evidence = list((await db.execute(select(Evidence).where(Evidence.event_id == event_id))).scalars())

        sem = asyncio.Semaphore(3)

        async def judge(ev: Evidence) -> list[dict]:
            if ev.is_primary and ev.origin == "primary":
                # The change was observed directly on the competitor's own property.
                return [
                    {
                        "claim_index": i,
                        "stance": "supports",
                        "rationale": "directly observed on primary source",
                    }
                    for i in range(len(claims))
                ]
            if not ev.snippet.strip():
                return []
            async with sem:
                j = await llm.complete(
                    "judge_evidence",
                    EvidenceJudgment,
                    {
                        "competitor": competitor.name if competitor else "",
                        "claims": claims,
                        "evidence_title": ev.title,
                        "evidence_text": ev.snippet,
                    },
                    tier="classify",
                )
            return [x.model_dump() for x in j.judgments if 0 <= x.claim_index < len(claims)]

        judgments = await asyncio.gather(*[judge(ev) for ev in evidence])
        names = competitor_names(competitor)
        for ev, js in zip(evidence, judgments, strict=True):
            for j in js:
                if not (ev.is_primary and ev.origin == "primary"):
                    grounded = grounded_stance(
                        j["stance"], claims[j["claim_index"]], f"{ev.title}\n{ev.snippet}", names
                    )
                    if grounded != j["stance"]:
                        j["rationale"] = f"[ungrounded {j['stance']} discarded] {j.get('rationale', '')}"
                        j["stance"] = grounded
            ev.stances = js

        result = score_evidence(claims, evidence)
        db.add(
            Verification(
                org_id=org_id,
                event_id=event_id,
                confidence_score=result.score,
                level=result.level.value,
                rationale=result.rationale,
                claims=claims_payload(result),
            )
        )
        event.confidence_score = result.score
        event.confidence_level = result.level.value
        event.stage = "analyzing"
        await db.commit()

    return {
        "confidence": {
            "score": result.score,
            "level": result.level.value,
            "rationale": result.rationale,
            "verified_claims": [cs.claim for cs in result.claims if cs.score >= 0.5],
        },
        "_summary": {
            "score": result.score,
            "level": result.level.value,
            "rationale": result.rationale,
            "evidence_judged": len(evidence),
        },
    }
