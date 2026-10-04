"""Daily intelligence brief graph:  gather -> summarize -> compose (per role) -> deliver."""

import uuid
from datetime import date, datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agents.runner import _claim_run, _finish_run
from app.agents.tracing import traced
from app.alerts.delivery import md_to_html, render_email, send_email, templates
from app.config import settings
from app.core.logging import get_logger
from app.core.telemetry import BRIEFS_GENERATED
from app.db.base import utcnow
from app.db.enums import BUSINESS_ROLES, PRIORITY_RANK, Priority, RunStatus
from app.db.models import AlertSubscription, Brief, Competitor, Event, ImpactAssessment, Organization, User
from app.db.session import tenant_session
from app.llm.client import get_llm
from app.llm.schemas import BriefSummary

log = get_logger(__name__)

ROLE_DEFAULT_CATEGORIES: dict[str, set[str] | None] = {
    "executive": None,
    "product": {"product", "feature", "partnership", "strategy"},
    "sales": {"pricing", "product", "feature", "partnership", "positioning"},
    "marketing": {"positioning", "product", "partnership", "pricing"},
    "pricing": {"pricing", "product", "financial"},
    "general": None,
}


class BriefState(TypedDict, total=False):
    org_id: str
    run_id: str
    brief_date: str
    window_hours: int
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    brief_ids: list[str]


@traced("brief_gather")
async def gather_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    since = utcnow() - timedelta(hours=state.get("window_hours", 24))
    async with tenant_session(org_id) as db:
        rows = (
            await db.execute(
                select(Event, Competitor, ImpactAssessment)
                .join(Competitor, Competitor.id == Event.competitor_id)
                .outerjoin(ImpactAssessment, ImpactAssessment.event_id == Event.id)
                .where(Event.detected_at >= since, Event.priority.is_not(None), Event.status != "dismissed")
            )
        ).all()
    events: list[dict[str, Any]] = [
        {
            "id": str(e.id),
            "title": e.title,
            "summary": e.summary,
            "category": e.category,
            "priority": e.priority,
            "priority_score": e.priority_score or 0,
            "competitor": c.name,
            "confidence_level": e.confidence_level,
            "link": f"{settings.frontend_url}/events/{e.id}",
            "simulated": e.is_simulated,
            "role_implications": ia.role_implications if ia else {},
            "actions": ia.recommended_actions if ia else [],
        }
        for e, c, ia in rows
    ]
    events.sort(
        key=lambda x: (-PRIORITY_RANK[Priority(str(x["priority"]))], -float(x["priority_score"] or 0))
    )
    return {"events": events, "_summary": {"events": len(events)}}


@traced("brief_summarize")
async def summarize_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    async with tenant_session(org_id) as db:
        org = await db.get(Organization, org_id)
    s = await get_llm().complete(
        "brief_summary",
        BriefSummary,
        {
            "org_name": org.name if org else "",
            "date": state["brief_date"],
            "events": state.get("events", [])[:25],
        },
    )
    return {"summary": s.model_dump(), "_summary": {"headline": s.headline}}


def _role_events(role: str, events: list[dict], subs: list[AlertSubscription]) -> list[dict]:
    role_subs = [
        s for s in subs if s.role == role and s.user_id is None and s.include_in_brief and s.is_active
    ]
    cats: set[str] | None = None
    if role_subs and all(s.categories for s in role_subs):
        cats = {c for s in role_subs for c in s.categories}
    elif not role_subs:
        cats = ROLE_DEFAULT_CATEGORIES.get(role)
    selected = [
        e for e in events if cats is None or e["category"] in cats or e["priority"] in ("critical",)
    ]  # critical items reach everyone
    return selected


def compose_markdown(*, role: str, org_name: str, brief_date: str, summary: dict, events: list[dict]) -> str:
    groups = []
    for label, prios in (
        ("Needs attention", ("critical", "high")),
        ("Worth knowing", ("medium",)),
        ("On the radar", ("low",)),
    ):
        evs = [e for e in events if e["priority"] in prios]
        if evs:
            key = role if role != "general" else "executive"
            groups.append(
                {
                    "label": label,
                    "events": [
                        {
                            **e,
                            "implication": (e.get("role_implications") or {}).get(key, ""),
                            "actions": [
                                a
                                for a in e.get("actions", [])
                                if role == "general" or a.get("owner_role") == key
                            ][:3],
                        }
                        for e in evs[:12]
                    ],
                }
            )
    by_p: dict[str, int] = {}
    for e in events:
        by_p[e["priority"]] = by_p.get(e["priority"], 0) + 1
    return templates.get_template("brief.md.j2").render(
        headline=summary.get("headline", "Daily brief"),
        executive_summary=summary.get("executive_summary", ""),
        key_themes=summary.get("key_themes", []),
        watch_list=summary.get("watch_list", []),
        org_name=org_name,
        date=brief_date,
        role=role,
        role_label=role if role != "general" else "the team",
        groups=groups,
        stats={"total": len(events), "by_priority": by_p},
    )


@traced("brief_compose")
async def compose_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    events = state.get("events", [])
    summary = state.get("summary", {})
    brief_date = date.fromisoformat(state["brief_date"])
    ids = []
    async with tenant_session(org_id) as db:
        org = await db.get(Organization, org_id)
        subs = list((await db.execute(select(AlertSubscription))).scalars())
        for role in ["general", *[r.value for r in BUSINESS_ROLES]]:
            evs = events if role == "general" else _role_events(role, events, subs)
            content = compose_markdown(
                role=role,
                org_name=org.name if org else "",
                brief_date=state["brief_date"],
                summary=summary,
                events=evs,
            )
            values = dict(
                id=uuid.uuid4(),
                org_id=org_id,
                brief_date=brief_date,
                role=role,
                title=summary.get("headline", "Daily brief")[:300],
                summary=summary.get("executive_summary", ""),
                content_md=content,
                content_html=md_to_html(content),
                event_ids=[e["id"] for e in evs],
                stats={"events": len(evs)},
                generated_at=utcnow(),
            )
            stmt = (
                insert(Brief)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_briefs_org_date_role",
                    set_={
                        k: values[k]
                        for k in (
                            "title",
                            "summary",
                            "content_md",
                            "content_html",
                            "event_ids",
                            "stats",
                            "generated_at",
                        )
                    },
                )
                .returning(Brief.id)
            )
            ids.append(str((await db.execute(stmt)).scalar_one()))
            BRIEFS_GENERATED.labels(role).inc()
        await db.commit()
    return {"brief_ids": ids, "_summary": {"briefs": len(ids)}}


@traced("brief_deliver")
async def deliver_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    brief_date = date.fromisoformat(state["brief_date"])
    sent = failed = 0
    async with tenant_session(org_id) as db:
        briefs = {
            b.role: b
            for b in (await db.execute(select(Brief).where(Brief.brief_date == brief_date))).scalars()
        }
        subs = list(
            (
                await db.execute(select(AlertSubscription).where(AlertSubscription.is_active.is_(True)))
            ).scalars()
        )
        users = list((await db.execute(select(User).where(User.is_active.is_(True)))).scalars())
        for u in users:
            wants = any(
                s.include_in_brief
                and "email" in (s.channels or [])
                and (s.user_id == u.id or (s.user_id is None and s.role == u.role))
                for s in subs
            )
            if not wants:
                continue
            brief = briefs.get(u.role) or briefs.get("general")
            if brief is None or brief.stats.get(f"emailed:{u.id}"):
                continue
            try:
                html = render_email(
                    title=brief.title,
                    kicker=f"Daily brief · {brief_date:%b %d, %Y}",
                    body_md=brief.content_md,
                    priority="medium",
                )
                await send_email(u.email, f"Daily CI brief — {brief.title}", html, brief.content_md)
                brief.stats = {**brief.stats, f"emailed:{u.id}": True}
                brief.emailed_at = utcnow()
                sent += 1
            except Exception as e:
                failed += 1
                log.warning("brief.email_failed", user=str(u.id), error=str(e)[:200])
        await db.commit()
    return {"_summary": {"emailed": sent, "failed": failed}}


def build_brief_graph():
    g = StateGraph(BriefState)
    g.add_node("gather", gather_node)
    g.add_node("summarize", summarize_node)
    g.add_node("compose", compose_node)
    g.add_node("deliver", deliver_node)
    g.add_edge(START, "gather")
    g.add_edge("gather", "summarize")
    g.add_edge("summarize", "compose")
    g.add_edge("compose", "deliver")
    g.add_edge("deliver", END)
    return g.compile()


async def generate_daily_brief(
    org_id: uuid.UUID,
    brief_date: date | None = None,
    *,
    deliver: bool = True,
    trigger: str = "schedule",
    window_hours: int = 24,
) -> dict[str, Any]:
    brief_date = brief_date or utcnow().date()
    key = f"brief:{org_id}:{brief_date.isoformat()}" if trigger == "schedule" else f"brief:{uuid.uuid4()}"
    run, _ = await _claim_run(org_id, "daily_brief", key, trigger, None)
    if run.status == RunStatus.succeeded:
        return {"run_id": str(run.id), "status": run.status, "idempotent_replay": True}
    graph = build_brief_graph()
    state: dict[str, Any] = {
        "org_id": str(org_id),
        "run_id": str(run.id),
        "brief_date": brief_date.isoformat(),
        "window_hours": window_hours,
    }
    try:
        if deliver:
            result = await graph.ainvoke(state)
        else:
            for node in (gather_node, summarize_node, compose_node):
                state.update(await node(state))
            result = state
    except Exception as e:
        await _finish_run(org_id, run.id, status=RunStatus.failed, error=str(e)[:4000])
        raise
    summary = {"brief_ids": result.get("brief_ids", []), "events": len(result.get("events", []))}
    await _finish_run(org_id, run.id, status=RunStatus.succeeded, outcome="brief_generated", summary=summary)
    return {"run_id": str(run.id), "status": "succeeded", **summary}


def brief_due(org: Organization, now: datetime, has_brief_today: bool) -> bool:
    return not has_brief_today and now.hour >= org.brief_hour_utc
