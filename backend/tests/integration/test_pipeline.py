"""End-to-end agent pipeline against real Postgres/pgvector with the network mocked (respx) and the
deterministic heuristic LLM provider."""

import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

pytestmark = pytest.mark.integration

PRICING = {"growth": 79}
BLOG_ITEMS: list[dict] = []
SENT_EMAILS: list[tuple[str, str]] = []


def pricing_html() -> str:
    return f"""<html><head><title>Acme — Pricing</title></head><body><main>
<h1>Pricing</h1><p>Analytics for teams</p>
<section><h3>Starter</h3><p>$29 / month</p><ul><li>✓ 5 dashboards</li><li>✓ Email support</li></ul></section>
<section><h3>Growth</h3><p>${PRICING["growth"]} / month</p><ul><li>✓ Unlimited dashboards</li><li>✓ SSO</li></ul></section>
<section><h3>Enterprise</h3><p>Contact sales</p><ul><li>✓ Audit logs</li></ul></section>
</main><footer>© 2026 Acme</footer></body></html>"""


def rss() -> str:
    items = "".join(
        f"<item><title>{i['title']}</title><link>http://acme.test/blog/{i['id']}</link><guid>{i['id']}</guid>"
        f"<description>{i['body']}</description></item>"
        for i in BLOG_ITEMS
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Acme blog</title>{items}</channel></rss>'


@pytest.fixture
def web():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://acme.test/pricing.html").mock(
            side_effect=lambda r: httpx.Response(
                200, text=pricing_html(), headers={"content-type": "text/html"}
            )
        )
        mock.get("http://acme.test/blog/rss.xml").mock(
            side_effect=lambda r: httpx.Response(
                200, text=rss(), headers={"content-type": "application/rss+xml"}
            )
        )
        mock.get(url__startswith="http://searxng.test/search").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        mock.get(url__startswith="https://api.gdeltproject.org/").mock(
            return_value=httpx.Response(200, json={"articles": []})
        )
        yield mock


@pytest.fixture
def capture_email(monkeypatch):
    async def fake_send(to, subject, html, text):  # noqa: ARG001
        SENT_EMAILS.append((to, subject))

    monkeypatch.setattr("app.alerts.router.send_email", fake_send)
    monkeypatch.setattr("app.agents.brief_graph.send_email", fake_send)
    SENT_EMAILS.clear()


@pytest.fixture
async def world(database):
    """An org with users per role, our company profile, one competitor and two sources."""
    from app.api.v1.auth import default_subscriptions
    from app.db.models import CompanyProfile, Competitor, Organization, OwnProduct, Source, User
    from app.db.session import system_session

    PRICING["growth"] = 79
    BLOG_ITEMS.clear()
    BLOG_ITEMS.append({"id": "p1", "title": "Customer story: faster reporting", "body": "A case study."})
    async with system_session() as db:
        org = Organization(name="Northwind", slug=f"nw-{uuid.uuid4().hex[:6]}", settings={})
        db.add(org)
        await db.flush()
        for role in ("admin", "executive", "sales", "pricing", "product", "marketing"):
            db.add(
                User(
                    org_id=org.id,
                    email=f"{role}-{uuid.uuid4().hex[:6]}@nw.example.com",
                    role=role,
                    full_name=role,
                )
            )
        db.add_all(default_subscriptions(org.id))
        db.add(CompanyProfile(org_id=org.id, name="Northwind", differentiators=["Onboarding"]))
        db.add(OwnProduct(org_id=org.id, name="Northwind Insights", category="BI"))
        comp = Competitor(org_id=org.id, name="Acme", domain="acme.test", threat_tier=5)
        db.add(comp)
        await db.flush()
        pricing = Source(
            org_id=org.id,
            competitor_id=comp.id,
            name="Pricing",
            source_type="pricing",
            url="http://acme.test/pricing.html",
        )
        blog = Source(
            org_id=org.id,
            competitor_id=comp.id,
            name="Blog",
            source_type="blog_rss",
            url="http://acme.test/blog/rss.xml",
        )
        db.add_all([pricing, blog])
        await db.commit()
        return {"org_id": org.id, "competitor_id": comp.id, "pricing_id": pricing.id, "blog_id": blog.id}


async def test_full_pipeline_detects_verifies_prioritises_and_alerts(world, web, capture_email):
    from app.agents.runner import run_intel_pipeline
    from app.db.models import AgentStep, Alert, Event, ImpactAssessment, PricePoint, Verification
    from app.db.session import tenant_session

    org_id = world["org_id"]

    # 1) Baseline: first snapshot, pricing learned into the knowledge base, no alerts.
    r1 = await run_intel_pipeline(org_id, world["pricing_id"], trigger="test")
    assert r1["scout_status"] == "first_snapshot" and r1["events"] == []

    # 2) No change -> skipped cheaply.
    r2 = await run_intel_pipeline(org_id, world["pricing_id"], trigger="test")
    assert r2["status"] == "skipped"

    # 3) Price hike -> full investigation.
    PRICING["growth"] = 99
    r3 = await run_intel_pipeline(org_id, world["pricing_id"], trigger="test")
    assert len(r3["events"]) == 1, r3

    async with tenant_session(org_id) as db:
        event = (await db.execute(select(Event))).scalar_one()
        assert event.category == "pricing"
        assert "raised 'Growth' price from $79/month to $99/month" in event.title
        assert event.confidence_level == "confirmed"  # directly observed on the competitor's own pricing page
        assert event.priority in ("high", "critical")
        assert event.stage == "complete"
        assert (await db.execute(select(Verification))).scalar_one().level == "confirmed"
        impact = (await db.execute(select(ImpactAssessment))).scalar_one()
        assert impact.priority_rationale.startswith("score")

        current = {
            p.plan: float(p.price)
            for p in (await db.execute(select(PricePoint).where(PricePoint.valid_to.is_(None)))).scalars()
            if p.price is not None
        }
        assert current["Growth"] == 99.0 and current["Starter"] == 29.0
        closed = (
            (await db.execute(select(PricePoint).where(PricePoint.valid_to.is_not(None)))).scalars().all()
        )
        assert [float(p.price) for p in closed] == [79.0]

        agents = [
            s.agent for s in (await db.execute(select(AgentStep).order_by(AgentStep.started_at))).scalars()
        ]
        for a in (
            "scout",
            "change_detection",
            "research",
            "verification",
            "knowledge",
            "impact",
            "prioritize",
            "alert",
        ):
            assert a in agents

        alerts = (await db.execute(select(Alert))).scalars().all()
        in_app = [a for a in alerts if a.channel == "in_app"]
        assert len(in_app) == 6  # every role subscription matched
        assert any("Talking points" in a.body_md for a in in_app)  # sales edition

    assert len(SENT_EMAILS) == 6  # high/critical -> immediate email

    # 4) The same move announced on the blog corroborates the existing event instead of re-alerting.
    await run_intel_pipeline(org_id, world["blog_id"], trigger="test")  # baseline for the feed
    BLOG_ITEMS.insert(
        0,
        {
            "id": "p2",
            "title": "Growth plan now $99 per month",
            "body": "Starting today Acme Growth costs $99 per month, previously $79.",
        },
    )
    r4 = await run_intel_pipeline(org_id, world["blog_id"], trigger="test")
    assert r4["events"] == [] and r4["outcome"] == "corroborated_existing_event"
    async with tenant_session(org_id) as db:
        assert len((await db.execute(select(Event))).scalars().all()) == 1
        assert len((await db.execute(select(Alert).where(Alert.channel == "in_app"))).scalars().all()) == 6


async def test_idempotent_replay_and_resume(world, web, capture_email):
    from app.agents.runner import run_intel_pipeline

    key = f"test:{uuid.uuid4()}"
    first = await run_intel_pipeline(world["org_id"], world["pricing_id"], idempotency_key=key)
    again = await run_intel_pipeline(world["org_id"], world["pricing_id"], idempotency_key=key)
    assert again["run_id"] == first["run_id"] and again.get("idempotent_replay") is True


async def test_rls_isolates_tenants(world):
    from app.db.models import Competitor, Organization
    from app.db.session import system_session, tenant_session

    async with system_session() as db:
        other = Organization(name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", settings={})
        db.add(other)
        await db.flush()
        db.add(Competitor(org_id=other.id, name="Secret Rival", domain="secret.test"))
        await db.commit()

    async with tenant_session(world["org_id"]) as db:
        names = {c.name for c in (await db.execute(select(Competitor))).scalars()}
        assert "Secret Rival" not in names and "Acme" in names
        # Writing a row into another tenant is rejected by the policy's WITH CHECK clause.
        db.add(Competitor(org_id=other.id, name="Injected", domain="x.test"))
        with pytest.raises(Exception, match="row-level security"):
            await db.commit()


async def test_daily_brief(world, web, capture_email):
    from app.agents.brief_graph import generate_daily_brief
    from app.agents.runner import run_intel_pipeline
    from app.db.models import Brief
    from app.db.session import tenant_session

    await run_intel_pipeline(world["org_id"], world["pricing_id"])
    PRICING["growth"] = 119
    await run_intel_pipeline(world["org_id"], world["pricing_id"])
    out = await generate_daily_brief(world["org_id"], deliver=True, trigger="manual")
    assert out["status"] == "succeeded" and len(out["brief_ids"]) == 6
    async with tenant_session(world["org_id"]) as db:
        briefs = {b.role: b for b in (await db.execute(select(Brief))).scalars()}
        assert set(briefs) == {"general", "executive", "product", "sales", "marketing", "pricing"}
        assert "Needs attention" in briefs["pricing"].content_md
    assert any("Daily CI brief" in subj for _, subj in SENT_EMAILS)
