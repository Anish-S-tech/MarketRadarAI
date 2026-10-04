"""Alert Agent core: routes a prioritised event to the right people through the right channels.

Routing = subscription match (role or personal) × category × competitor × minimum priority.
Critical/high events are emailed immediately (subject to per-user throttling); lower priorities are
delivered in-app now and batched into the next daily brief email.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.delivery import publish_in_app, render_email, send_email, templates
from app.config import settings
from app.core.logging import get_logger
from app.core.telemetry import ALERTS_SENT
from app.db.base import utcnow
from app.db.enums import PRIORITY_RANK, AlertChannel, AlertStatus, Priority, Role
from app.db.models import (
    Alert,
    AlertSubscription,
    Change,
    CompanyProfile,
    Competitor,
    Event,
    Evidence,
    ImpactAssessment,
    User,
)

log = get_logger(__name__)

ROLE_LABELS = {
    "executive": "leadership",
    "product": "product",
    "sales": "sales",
    "marketing": "marketing",
    "pricing": "pricing",
    "admin": "you",
}


def subscription_matches(sub: AlertSubscription, event: Event) -> bool:
    if not sub.is_active or event.priority is None:
        return False
    if PRIORITY_RANK[Priority(event.priority)] < PRIORITY_RANK[Priority(sub.min_priority)]:
        return False
    if sub.categories and event.category not in sub.categories:
        return False
    return not (sub.competitor_ids and str(event.competitor_id) not in {str(c) for c in sub.competitor_ids})


def render_alert_body(role: str, ctx: dict[str, Any]) -> str:
    implications = ctx.get("role_implications", {})
    actions = ctx.get("actions", [])
    mine = [a for a in actions if a.get("owner_role") == role]
    return templates.get_template("alert.md.j2").render(
        {
            **ctx,
            "role": role,
            "role_label": ROLE_LABELS.get(role, role),
            "implication": implications.get(role) or implications.get("executive", ""),
            "actions": (mine or actions)[:4],
        }
    )


async def build_context(db: AsyncSession, event: Event) -> dict[str, Any]:
    competitor = await db.get(Competitor, event.competitor_id)
    impact = (
        await db.execute(select(ImpactAssessment).where(ImpactAssessment.event_id == event.id))
    ).scalar_one_or_none()
    change = await db.get(Change, event.change_id) if event.change_id else None
    company = (await db.execute(select(CompanyProfile).limit(1))).scalar_one_or_none()
    evidence = list(
        (
            await db.execute(
                select(Evidence)
                .where(Evidence.event_id == event.id)
                .order_by(Evidence.reliability_tier, Evidence.created_at)
            )
        ).scalars()
    )
    supporting = [e for e in evidence if any(s.get("stance") == "supports" for s in e.stances)] or evidence
    return {
        "priority": event.priority or "low",
        "competitor": competitor.name if competitor else "",
        "category": event.category,
        "confidence_level": event.confidence_level,
        "confidence_score": event.confidence_score,
        "summary": (impact.summary if impact and impact.summary else event.summary),
        "key_facts": event.key_facts,
        "pricing_changes": change.diff.get("pricing_changes", []) if change else [],
        "role_implications": impact.role_implications if impact else {},
        "actions": impact.recommended_actions if impact else [],
        "differentiators": company.differentiators if company else [],
        "evidence": [
            {
                "title": e.title,
                "url": e.url,
                "domain": e.domain,
                "tier": e.reliability_tier,
                "primary": e.is_primary,
            }
            for e in supporting[:3]
        ],
        "link": f"{settings.frontend_url}/events/{event.id}",
        "simulated": event.is_simulated,
    }


async def _emails_sent_last_hour(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.user_id == user_id,
                Alert.channel == AlertChannel.email,
                Alert.status == AlertStatus.sent,
                Alert.sent_at >= utcnow() - timedelta(hours=1),
            )
        )
    ).scalar_one()


async def _already_alerted_similar(db: AsyncSession, user_id: uuid.UUID, event: Event) -> bool:
    """Dedupe across events: same user already got an alert for an event with the same dedupe key recently."""
    return (
        await db.execute(
            select(func.count())
            .select_from(Alert)
            .join(Event, Event.id == Alert.event_id)
            .where(
                Alert.user_id == user_id,
                Event.dedupe_key == event.dedupe_key,
                Event.id != event.id,
                Alert.created_at >= utcnow() - timedelta(hours=settings.alert_dedupe_hours),
            )
        )
    ).scalar_one() > 0


async def _insert_alert(db: AsyncSession, **values: Any) -> uuid.UUID | None:
    stmt = (
        insert(Alert)
        .values(id=uuid.uuid4(), **values)
        .on_conflict_do_nothing(constraint="uq_alerts_user_event_channel")
        .returning(Alert.id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def dispatch_event_alerts(db: AsyncSession, event_id: uuid.UUID) -> dict[str, int]:
    event = await db.get(Event, event_id)
    if event is None or event.priority is None:
        return {}
    subs = list(
        (await db.execute(select(AlertSubscription).where(AlertSubscription.is_active.is_(True)))).scalars()
    )
    users = {u.id: u for u in (await db.execute(select(User).where(User.is_active.is_(True)))).scalars()}

    # Resolve recipients -> channels (union across matching subscriptions).
    recipients: dict[uuid.UUID, set[str]] = {}
    for sub in subs:
        if not subscription_matches(sub, event):
            continue
        targets = (
            [users[sub.user_id]]
            if sub.user_id and sub.user_id in users
            else [u for u in users.values() if sub.user_id is None and u.role == sub.role]
        )
        for u in targets:
            recipients.setdefault(u.id, set()).update(sub.channels or [])

    ctx = await build_context(db, event)
    counts = {
        "in_app": 0,
        "email_sent": 0,
        "email_deferred": 0,
        "email_throttled": 0,
        "email_failed": 0,
        "deduped": 0,
    }
    email_now = (
        PRIORITY_RANK[Priority(event.priority)]
        >= PRIORITY_RANK[Priority(settings.email_immediate_min_priority)]
    )
    title = f"[{event.priority.upper()}]{' [SIMULATED]' if event.is_simulated else ''} {event.title}"

    for user_id, channels in recipients.items():
        user = users[user_id]
        if await _already_alerted_similar(db, user_id, event):
            counts["deduped"] += 1
            continue
        role = user.role if user.role != Role.admin else "executive"
        body = render_alert_body(role, ctx)

        if AlertChannel.in_app in channels:
            alert_id = await _insert_alert(
                db,
                org_id=event.org_id,
                user_id=user_id,
                event_id=event.id,
                channel=AlertChannel.in_app.value,
                priority=event.priority,
                title=title,
                body_md=body,
                status=AlertStatus.sent.value,
                sent_at=utcnow(),
            )
            if alert_id:
                counts["in_app"] += 1
                ALERTS_SENT.labels("in_app", "sent").inc()
                await publish_in_app(
                    user_id,
                    {
                        "type": "alert",
                        "alert_id": str(alert_id),
                        "event_id": str(event.id),
                        "title": title,
                        "priority": event.priority,
                        "category": event.category,
                        "competitor": ctx["competitor"],
                    },
                )

        if AlertChannel.email in channels:
            status, error, sent_at = AlertStatus.deferred, None, None
            if email_now:
                if await _emails_sent_last_hour(db, user_id) >= settings.email_max_per_user_per_hour:
                    status = AlertStatus.throttled
                else:
                    try:
                        html = render_email(
                            title=event.title,
                            kicker=f"{event.priority} · {ctx['competitor']} · {event.category}",
                            body_md=body,
                            priority=event.priority,
                        )
                        await send_email(user.email, title, html, body)
                        status, sent_at = AlertStatus.sent, utcnow()
                    except Exception as e:
                        status, error = AlertStatus.failed, str(e)[:500]
                        log.warning("alert.email_failed", user=str(user_id), error=error)
            alert_id = await _insert_alert(
                db,
                org_id=event.org_id,
                user_id=user_id,
                event_id=event.id,
                channel=AlertChannel.email.value,
                priority=event.priority,
                title=title,
                body_md=body,
                status=status.value,
                error=error,
                sent_at=sent_at,
            )
            if alert_id:
                key = {
                    "sent": "email_sent",
                    "deferred": "email_deferred",
                    "throttled": "email_throttled",
                    "failed": "email_failed",
                }[status.value]
                counts[key] += 1
                ALERTS_SENT.labels("email", status.value).inc()

    return counts
