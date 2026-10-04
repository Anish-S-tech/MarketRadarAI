"""Operational CLI.

python -m app.cli migrate                 # alembic upgrade head + LangGraph checkpoint tables
python -m app.cli seed-demo               # demo org, users, our company, 3 competitors + sources
python -m app.cli run-source <source_id>  # run the full agent pipeline inline for one source
python -m app.cli run-all [--org <id>]    # run every active source inline (sequential)
python -m app.cli brief <org id or slug>   # generate (and email) today's brief inline
python -m app.cli dispatch                # one scheduler tick
    python -m app.cli seed-market [--replace] # real BI-market competitors + SimWire simulated feeds
"""

import argparse
import asyncio
import json
import os
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.core.logging import configure_logging


def migrate() -> None:
    from alembic.config import Config

    from alembic import command
    from app.agents.graph import setup_checkpointer

    cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    cfg.set_main_option(
        "script_location", os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic")
    )
    command.upgrade(cfg, "head")
    asyncio.run(setup_checkpointer())
    print("migrations + checkpointer setup complete")


DEMO_PASSWORD = "MarketRadar!2026"


async def seed_demo(base: str) -> None:
    from app.api.v1.auth import default_subscriptions
    from app.core.security import hash_password
    from app.db.models import (
        CompanyProfile,
        Competitor,
        CustomerSegment,
        Organization,
        OwnPricePoint,
        OwnProduct,
        Source,
        User,
    )
    from app.db.session import system_session

    async with system_session() as db:
        if (
            await db.execute(select(Organization).where(Organization.slug == "northwind"))
        ).scalar_one_or_none():
            print("demo org already exists")
            return
        org = Organization(
            name="Northwind Analytics",
            slug="northwind",
            brief_hour_utc=7,
            settings={"domain_tiers": {"localtest.me": 3}},
        )
        db.add(org)
        await db.flush()
        for role, email, name in [
            ("admin", "admin@northwind.example.com", "Ada Admin"),
            ("executive", "ceo@northwind.example.com", "Evan Exec"),
            ("product", "pm@northwind.example.com", "Priya Product"),
            ("sales", "sales@northwind.example.com", "Sam Sales"),
            ("marketing", "marketing@northwind.example.com", "Maya Marketing"),
            ("pricing", "pricing@northwind.example.com", "Pat Pricing"),
        ]:
            db.add(
                User(
                    org_id=org.id,
                    email=email,
                    full_name=name,
                    role=role,
                    hashed_password=hash_password(DEMO_PASSWORD),
                )
            )
        db.add_all(default_subscriptions(org.id))
        db.add(
            CompanyProfile(
                org_id=org.id,
                name="Northwind Analytics",
                website="https://northwind.example",
                description="Self-serve BI and analytics platform for mid-market companies.",
                positioning="The fastest way for business teams to get trustworthy answers from their data.",
                differentiators=[
                    "AI-assisted insights",
                    "Transparent per-workspace pricing",
                    "Best-in-class onboarding",
                ],
                target_markets=["Mid-market SaaS", "Retail", "Fintech"],
            )
        )
        insights = OwnProduct(
            org_id=org.id,
            name="Northwind Insights",
            category="BI platform",
            description="Dashboards, reports and AI summaries for business teams.",
            features=["Dashboards", "Hourly refresh", "SSO", "AI summaries", "API access"],
        )
        embed = OwnProduct(
            org_id=org.id,
            name="Northwind Embed",
            category="Embedded analytics",
            description="Embed Northwind dashboards inside your own SaaS product.",
            features=["White-labeling", "Row-level security", "React SDK"],
        )
        db.add_all([insights, embed])
        await db.flush()
        for plan, price in [("Starter", "25"), ("Pro", "69"), ("Enterprise", None)]:
            db.add(
                OwnPricePoint(
                    org_id=org.id, product_id=insights.id, plan=plan, price=Decimal(price) if price else None
                )
            )
        db.add(OwnPricePoint(org_id=org.id, product_id=embed.id, plan="Embed Pro", price=Decimal("149")))
        for name, desc, share in [
            ("SMB", "Teams under 100 employees", 0.35),
            ("Mid-market", "100-2000 employees, our core segment", 0.45),
            ("Enterprise", "2000+ employees", 0.20),
        ]:
            db.add(CustomerSegment(org_id=org.id, name=name, description=desc, revenue_share=share))

        comps = [
            (
                "Acme Insights",
                "acme.localtest.me",
                5,
                "Closest head-to-head rival in self-serve BI.",
                ["SMB", "Mid-market"],
            ),
            (
                "Globex Data",
                "globex.localtest.me",
                4,
                "Enterprise data governance vendor moving down-market.",
                ["Enterprise"],
            ),
            (
                "Initech Cloud",
                "initech.localtest.me",
                3,
                "Embedded analytics specialist; competes with Northwind Embed.",
                ["Mid-market"],
            ),
        ]
        for name, domain, tier, desc, segs in comps:
            c = Competitor(
                org_id=org.id, name=name, domain=domain, threat_tier=tier, description=desc, segments=segs
            )
            db.add(c)
            await db.flush()
            host = f"http://{domain}:8090"
            db.add_all(
                [
                    Source(
                        org_id=org.id,
                        competitor_id=c.id,
                        name="Pricing page",
                        source_type="pricing",
                        url=f"{host}/pricing.html",
                        check_interval_minutes=30,
                    ),
                    Source(
                        org_id=org.id,
                        competitor_id=c.id,
                        name="Blog",
                        source_type="blog_rss",
                        url=f"{host}/blog/rss.xml",
                        check_interval_minutes=30,
                    ),
                    Source(
                        org_id=org.id,
                        competitor_id=c.id,
                        name="Product page",
                        source_type="webpage",
                        url=f"{host}/product.html",
                        check_interval_minutes=60,
                    ),
                ]
            )
            if name == "Acme Insights":
                db.add(
                    Source(
                        org_id=org.id,
                        competitor_id=c.id,
                        name="TechNewswire (press)",
                        source_type="news",
                        url=f"{base.replace('{site}', 'newswire')}/rss.xml",
                        check_interval_minutes=30,
                    )
                )
        await db.commit()
        print(f"seeded demo org {org.id}; log in as admin@northwind.example.com / {DEMO_PASSWORD}")


async def run_source(source_id: str) -> None:
    from app.agents.runner import run_intel_pipeline
    from app.db.models import Source
    from app.db.session import system_session

    async with system_session() as db:
        src = await db.get(Source, uuid.UUID(source_id))
        assert src, "source not found"
        org_id = src.org_id
    result = await run_intel_pipeline(org_id, uuid.UUID(source_id), trigger="cli")
    print(json.dumps(result, indent=2, default=str))


async def run_all(org: str | None) -> None:
    from app.agents.runner import run_intel_pipeline
    from app.db.models import Source
    from app.db.session import system_session

    async with system_session() as db:
        stmt = select(Source).where(Source.is_active.is_(True)).order_by(Source.created_at)
        if org:
            stmt = stmt.where(Source.org_id == uuid.UUID(org))
        sources = [(s.org_id, s.id, s.name) for s in (await db.execute(stmt)).scalars()]
    for org_id, sid, name in sources:
        try:
            r = await run_intel_pipeline(org_id, sid, trigger="cli")
        except Exception as e:  # keep going; the run is recorded as failed and can be retried
            print(f"{name:<28} FAILED     {type(e).__name__}: {str(e)[:200]}")
            continue
        events = ", ".join(f"[{e['priority']}] {e['title']}" for e in r.get("events", []))
        print(f"{name:<28} {r['status']:<10} {r.get('outcome') or '':<22} {events}")


async def brief(org: str, deliver: bool) -> None:
    """`org` is an organisation id or slug."""
    from app.agents.brief_graph import generate_daily_brief
    from app.db.models import Organization
    from app.db.session import system_session

    try:
        org_id = uuid.UUID(org)
    except ValueError:
        async with system_session() as db:
            org_id = (await db.execute(select(Organization.id).where(Organization.slug == org))).scalar_one()
    result = await generate_daily_brief(org_id, deliver=deliver, trigger="manual")
    print(json.dumps(result, default=str))


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser(prog="marketradar")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    s = sub.add_parser("seed-demo")
    s.add_argument("--sites", default="http://{site}.localtest.me:8090")
    s = sub.add_parser("run-source")
    s.add_argument("source_id")
    s = sub.add_parser("run-all")
    s.add_argument("--org")
    s = sub.add_parser("brief")
    s.add_argument("org", help="organisation id or slug")
    s.add_argument("--no-deliver", action="store_true")
    sub.add_parser("dispatch")
    s = sub.add_parser("seed-market")
    s.add_argument("--replace", action="store_true", help="remove existing competitors first")
    s.add_argument("--no-impact", action="store_true", help="skip LLM impact analysis of historical events")
    a = p.parse_args()

    if a.cmd == "migrate":
        migrate()
    elif a.cmd == "seed-demo":
        asyncio.run(seed_demo(a.sites))
    elif a.cmd == "run-source":
        asyncio.run(run_source(a.source_id))
    elif a.cmd == "run-all":
        asyncio.run(run_all(a.org))
    elif a.cmd == "brief":
        asyncio.run(brief(a.org, not a.no_deliver))
    elif a.cmd == "seed-market":
        from app.demo.market import seed_market

        print(json.dumps(asyncio.run(seed_market(replace=a.replace, with_impact=not a.no_impact)), indent=2))
    elif a.cmd == "dispatch":
        from app.workers.tasks import _dispatch_due

        print(asyncio.run(_dispatch_due()))
    _ = settings


if __name__ == "__main__":
    main()
