"""Research Agent: opens an intelligence event for a significant change and autonomously gathers
corroborating material from the web, news, other monitored sources and the knowledge base."""

import asyncio
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.agents.nodes.verification import recompute_confidence
from app.agents.scoring import (
    grounded_stance,
    host_domain,
    is_own_domain,
    registrable_domain,
    reliability_tier,
)
from app.agents.tracing import traced
from app.config import settings
from app.db.base import utcnow
from app.db.models import (
    Change,
    Competitor,
    Event,
    Evidence,
    KBChunk,
    Organization,
    Snapshot,
    Source,
    Verification,
)
from app.db.session import tenant_session
from app.knowledge import kb_service
from app.knowledge.retrieval import hybrid_search, search_monitored_sources
from app.llm.client import get_llm
from app.llm.schemas import ResearchPlan
from app.monitoring.collector import quick_fetch_text
from app.monitoring.fetchers.http import make_client
from app.monitoring.search import best_passage, news_search, searxng_search

DEDUPE_WINDOW = timedelta(days=7)
RECENT_WINDOW = timedelta(hours=72)
LEXICAL_DUP_OVERLAP = 0.6
SEMANTIC_DUP_SIMILARITY = 0.92
SEMANTIC_DUP_SAME_CATEGORY = 0.82
_STOP = set(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "on",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "its",
        "new",
        "now",
        "from",
        "has",
        "have",
    ]
)


def dedupe_key(competitor_id: uuid.UUID, category: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{competitor_id}:{category}:{slug[:120]}"


def keywords(text: str, exclude: str = "", n: int = 6) -> list[str]:
    ex = set(exclude.lower().split())
    toks = [t for t in re.findall(r"[a-z0-9$%.]{3,}", text.lower()) if t not in _STOP and t not in ex]
    seen: list[str] = []
    for t in toks:
        if t not in seen:
            seen.append(t)
    return seen[:n]


def signature(text: str) -> set[str]:
    """Distinctive tokens of a development: money/percent/numbers and capitalised names."""
    nums = {n.replace(",", "") for n in re.findall(r"[$€£]?\d[\d,]*(?:\.\d+)?%?", text)}
    names = {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z0-9]{2,}\b", text)}
    return nums | names


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


async def _find_duplicate(
    db, competitor: Competitor, category: str, key: str, text: str, simulated: bool = False
) -> Event | None:
    """Same development seen through a different source (pricing page vs. blog post vs. press release).
    Simulated and real events never corroborate each other."""
    since = utcnow() - DEDUPE_WINDOW
    exact = (
        await db.execute(
            select(Event)
            .where(Event.dedupe_key == key, Event.detected_at >= since, Event.is_simulated.is_(simulated))
            .limit(1)
        )
    ).scalar_one_or_none()
    if exact:
        return exact
    recent = list(
        (
            await db.execute(
                select(Event)
                .where(
                    Event.competitor_id == competitor.id,
                    Event.detected_at >= utcnow() - RECENT_WINDOW,
                    Event.is_simulated.is_(simulated),
                )
                .order_by(Event.detected_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    if not recent:
        return None
    competitor_tokens = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", competitor.name)}
    sig = signature(text) - competitor_tokens
    for e in recent:
        other = signature(" ".join([e.title, e.summary, *e.key_facts])) - competitor_tokens
        if len(sig & other) >= 2 and _overlap(sig, other) >= LEXICAL_DUP_OVERLAP:
            return e
    vectors = await get_llm().embed([text])
    if not vectors:
        return None
    dist = KBChunk.embedding.cosine_distance(vectors[0])
    row = (
        await db.execute(
            select(KBChunk.ref_id, dist.label("d"))
            .where(
                KBChunk.kind == "event",
                KBChunk.ref_id.in_([e.id for e in recent]),
                KBChunk.embedding.is_not(None),
            )
            .order_by(dist)
            .limit(1)
        )
    ).first()
    if row and row.ref_id:
        sim = 1 - float(row.d)
        match = next(e for e in recent if e.id == row.ref_id)
        if sim >= SEMANTIC_DUP_SIMILARITY or (
            sim >= SEMANTIC_DUP_SAME_CATEGORY and match.category == category
        ):
            return match
    return None


async def _gather_web(queries: list[str], claims: list[str], exclude_urls: set[str]) -> list[dict]:
    async with make_client() as client:
        batches = await asyncio.gather(
            *[searxng_search(client, q, limit=4) for q in queries[:3]],
            news_search(client, queries[0], limit=4) if queries else asyncio.sleep(0, result=[]),
        )
        seen = set(exclude_urls)
        results: list[dict] = []
        for batch in batches:
            for r in batch:
                if r["url"] and r["url"] not in seen:
                    seen.add(r["url"])
                    results.append(r)
        results = results[: settings.research_max_results]
        sem = asyncio.Semaphore(4)

        async def enrich(r: dict) -> dict:
            async with sem:
                try:
                    title, text = await quick_fetch_text(client, r["url"])
                except Exception:
                    title, text = "", ""
            body = text if len(text) > len(r.get("content", "")) else r.get("content", "")
            return {**r, "title": r.get("title") or title, "text": f"{r.get('title', '')}\n{body}"}

        return list(await asyncio.gather(*[enrich(r) for r in results]))


@traced("research")
async def research_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    change_id = uuid.UUID(state["change_id"])

    async with tenant_session(org_id) as db:
        change = await db.get(Change, change_id)
        assert change is not None
        source = await db.get(Source, change.source_id)
        competitor = await db.get(Competitor, change.competitor_id)
        org = await db.get(Organization, org_id)
        assert source and competitor and org

        key = dedupe_key(competitor.id, change.category, change.title)
        item = change.diff.get("item") or {}
        dup_text = "\n".join(
            [change.title, change.summary, *change.key_facts, item.get("title", ""), item.get("summary", "")]
        )
        dup = await _find_duplicate(
            db,
            competitor,
            change.category,
            key,
            dup_text,
            simulated=bool((source.config or {}).get("simulated")),
        )
        primary_url = item.get("url") or source.url
        overrides = (org.settings or {}).get("domain_tiers", {})
        if dup is not None:
            # Same development seen through another source: attach it as corroboration of the existing event
            # (grounded against that event's claims), re-score confidence, and do not alert again.
            ver = (
                await db.execute(select(Verification).where(Verification.event_id == dup.id))
            ).scalar_one_or_none()
            dup_claims = [c["claim"] for c in ver.claims] if ver else [dup.title]
            snippet = "\n".join(
                p
                for p in [item.get("title", ""), item.get("summary", ""), change.summary, *change.key_facts]
                if p
            )[:2000]
            names = [competitor.name, *(competitor.aliases or []), competitor.domain.split(":")[0]]
            stances = [
                {
                    "claim_index": i,
                    "stance": grounded_stance("supports", claim, snippet, names),
                    "rationale": "corroborating sighting from another monitored source",
                }
                for i, claim in enumerate(dup_claims)
            ]
            db.add(
                Evidence(
                    org_id=org_id,
                    event_id=dup.id,
                    url=primary_url,
                    domain=host_domain(primary_url),
                    title=item.get("title") or f"{competitor.name} — {source.name}",
                    snippet=snippet,
                    origin="monitored",
                    reliability_tier=reliability_tier(primary_url, competitor.domain, overrides),
                    is_primary=is_own_domain(primary_url, competitor.domain),
                    stances=stances,
                )
            )
            await db.flush()
            rescored = await recompute_confidence(db, dup)
            if change.kind == "pricing":
                # The pricing page gives the precise, structured view of the move: keep price history exact.
                snap = await db.get(Snapshot, change.snapshot_id)
                plans = (snap.structured.get("pricing") or {}).get("plans", []) if snap else []
                if snap and plans:
                    await kb_service.sync_price_points(
                        db,
                        org_id,
                        competitor.id,
                        plans,
                        event_id=dup.id,
                        snapshot_id=snap.id,
                        observed_at=snap.fetched_at,
                    )
                facts = [pc["description"] for pc in change.diff.get("pricing_changes", [])]
                dup.key_facts = facts + [f for f in dup.key_facts if f not in facts]
            change.diff = {**change.diff, "duplicate_of": str(dup.id)}
            await db.commit()
            return {
                "duplicate_of": str(dup.id),
                "event_id": None,
                "duplicates": [{"change_id": str(change.id), "duplicate_of": str(dup.id)}],
                "_summary": {
                    "duplicate_of": str(dup.id),
                    "title": change.title,
                    "rescored": {"score": rescored.score, "level": rescored.level.value}
                    if rescored
                    else None,
                },
            }

        event = Event(
            org_id=org_id,
            competitor_id=competitor.id,
            change_id=change.id,
            source_id=source.id,
            title=change.title,
            summary=change.summary,
            category=change.category,
            key_facts=change.key_facts,
            dedupe_key=key,
            stage="researching",
            agent_run_id=uuid.UUID(state["run_id"]),
            is_simulated=bool((source.config or {}).get("simulated")),
        )
        db.add(event)
        await db.flush()

        plan = await get_llm().complete(
            "research_plan",
            ResearchPlan,
            {
                "competitor": competitor.name,
                "title": change.title,
                "summary": change.summary,
                "key_facts": change.key_facts,
                "category": change.category,
                "max_claims": settings.research_max_claims,
            },
        )
        claims = (
            [c.strip() for c in plan.claims if c.strip()][: settings.research_max_claims]
            or change.key_facts[:1]
            or [change.title]
        )
        queries = [q for q in plan.queries if q.strip()][:4] or [change.title]

        evidence_rows: list[Evidence] = []

        # 1) Primary evidence: the monitored source itself, where the change was directly observed.
        if change.kind in ("diff", "pricing"):
            primary_text = "\n".join(
                [pc["description"] for pc in change.diff.get("pricing_changes", [])]
                + change.diff.get("added", [])[:30]
            )
        else:
            primary_text = f"{item.get('title', '')}\n{item.get('summary', '')}"
        is_primary = (
            is_own_domain(primary_url, competitor.domain) or registrable_domain(primary_url) == "sec.gov"
        )
        evidence_rows.append(
            Evidence(
                org_id=org_id,
                event_id=event.id,
                url=primary_url,
                domain=host_domain(primary_url),
                title=item.get("title") or f"{competitor.name} — {source.name}",
                snippet=primary_text[:2000],
                origin="primary" if is_primary else "monitored",
                published_at=None,
                reliability_tier=reliability_tier(primary_url, competitor.domain, overrides),
                is_primary=is_primary,
            )
        )

        # 2) Other monitored sources (e.g. the competitor's blog announcing the pricing change).
        kw = keywords(" ".join([change.title, *claims]), exclude=competitor.name)
        monitored = await search_monitored_sources(
            db,
            " or ".join([competitor.name.lower(), *kw]),
            exclude_source_id=source.id,
            competitor_id=competitor.id,
            limit=3,
        )
        for m in monitored:
            evidence_rows.append(
                Evidence(
                    org_id=org_id,
                    event_id=event.id,
                    url=m["url"],
                    domain=host_domain(m["url"]),
                    title=m["title"],
                    snippet=best_passage(m["text"], claims),
                    origin="monitored",
                    reliability_tier=reliability_tier(m["url"], competitor.domain, overrides),
                    is_primary=is_own_domain(m["url"], competitor.domain),
                )
            )

        # 3) Open web + news.
        web = await _gather_web(queries, claims, exclude_urls={e.url for e in evidence_rows})
        for w in web:
            evidence_rows.append(
                Evidence(
                    org_id=org_id,
                    event_id=event.id,
                    url=w["url"][:2000],
                    domain=host_domain(w["url"]),
                    title=(w.get("title") or "")[:500],
                    snippet=best_passage(w["text"], claims),
                    origin=w["origin"],
                    reliability_tier=reliability_tier(w["url"], competitor.domain, overrides),
                    is_primary=is_own_domain(w["url"], competitor.domain),
                )
            )
        for ev in evidence_rows:
            db.add(ev)

        # 4) Competitive memory for downstream agents.
        kb = await hybrid_search(
            db,
            f"{change.title}\n{change.summary}",
            competitor_id=competitor.id,
            exclude_ref_ids=[event.id],
            limit=6,
        )
        event.stage = "verifying"
        await db.commit()

    kb_context = [
        {
            "title": k["title"],
            "content": k["content"][:600],
            "kind": k["kind"],
            "occurred_at": k["occurred_at"],
        }
        for k in kb
    ]
    return {
        "event_id": str(event.id),
        "claims": claims,
        "kb_context": kb_context,
        "_summary": {
            "claims": claims,
            "queries": queries,
            "evidence": len(evidence_rows),
            "by_origin": {
                o: sum(1 for e in evidence_rows if e.origin == o) for o in {e.origin for e in evidence_rows}
            },
            "kb_hits": len(kb_context),
        },
    }
