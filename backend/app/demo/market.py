"""BI-market demo dataset: real, well-known competitors with real public history.

What is seeded here is intended to be public record (products, list prices, acquisitions, launches) at its
real date, stored as already-verified knowledge. Nothing in this module is simulated; recent *simulated*
developments come only from the SimWire feed (scripts/simwire.py) and go through the real agent pipeline,
which flags them `is_simulated`.

Power BI price history starts at the Premium Per User GA (April 2021); earlier Pro pricing is not modelled.
Prices are list prices as publicly advertised at the time of writing — the live pricing-page sources keep
them current. Where a vendor does not publish list prices (or they could not be stated confidently), no
price is seeded and the pricing monitor fills it in from the real page.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select

from app.agents.scoring import prioritize
from app.api.v1.auth import default_subscriptions
from app.core.security import hash_password
from app.db.base import utcnow
from app.db.models import (
    AgentRun,
    Brief,
    CompanyProfile,
    Competitor,
    CompetitorProduct,
    CompetitorRelationship,
    CustomerSegment,
    Event,
    Evidence,
    ImpactAssessment,
    KBChunk,
    Organization,
    OwnPricePoint,
    OwnProduct,
    PricePoint,
    ProductFeature,
    Source,
    User,
    Verification,
)
from app.db.session import system_session
from app.knowledge import kb_service
from app.llm.client import get_llm
from app.llm.schemas import ImpactAnalysis
from app.monitoring.fetchers.feeds import gdelt_url

DEMO_PASSWORD = "MarketRadar!2026"
SIMWIRE = "http://simwire.localtest.me:8090"


def d(s: str) -> datetime:
    """ISO date, or "observed" for facts whose start date is unknown (dated at seed time)."""
    return utcnow() if s == "observed" else datetime.fromisoformat(s).replace(tzinfo=UTC)


@dataclass
class Price:
    plan: str
    price: str | None
    valid_from: str
    valid_to: str | None = None
    period: str = "month"
    features: list[str] = field(default_factory=list)


@dataclass
class HistoricEvent:
    date: str
    title: str
    summary: str
    category: str
    facts: list[str]
    reference: str  # a public page about the subject (evidence URL)


@dataclass
class Rival:
    slug: str
    name: str
    domain: str
    tier: int
    description: str
    segments: list[str]
    ticker: str | None
    cik: str | None
    pricing_url: str | None
    news_query: str
    products: list[tuple[str, str, str, list[str]]]  # (name, category, description, features)
    prices: list[Price]
    relationships: list[tuple[str, str, str]]  # (counterparty, rel_type, description)
    history: list[HistoricEvent]
    aliases: list[str] = field(default_factory=list)


RIVALS: list[Rival] = [
    Rival(
        slug="powerbi",
        name="Microsoft Power BI",
        domain="powerbi.microsoft.com",
        aliases=["Power BI", "Microsoft Fabric"],
        tier=5,
        description="Microsoft's BI platform, part of Microsoft Fabric and bundled with Microsoft 365 E5. "
        "The default choice in Microsoft-centric organisations; competes on price and ecosystem reach.",
        segments=["SMB", "Mid-market", "Enterprise"],
        ticker="MSFT",
        cik="789019",
        pricing_url="https://www.microsoft.com/en-us/power-platform/products/power-bi/pricing",
        news_query='("Power BI" OR "Microsoft Fabric")',
        products=[
            (
                "Power BI Desktop",
                "Authoring",
                "Free Windows app for building reports and data models.",
                ["Report authoring", "DAX data modelling", "Power Query data preparation"],
            ),
            (
                "Power BI Pro",
                "BI platform",
                "Per-user licence to publish, share and collaborate on reports.",
                ["Sharing and collaboration", "Workspaces", "Scheduled refresh", "Microsoft 365 integration"],
            ),
            (
                "Power BI Premium Per User",
                "BI platform",
                "Per-user licence with Premium capabilities.",
                [
                    "Paginated reports",
                    "Larger semantic models",
                    "Deployment pipelines",
                    "More frequent refresh",
                ],
            ),
            (
                "Microsoft Fabric",
                "Data platform",
                "Unified SaaS analytics platform that includes Power BI.",
                ["OneLake", "Data Factory", "Data Warehouse", "Real-Time Intelligence"],
            ),
            (
                "Copilot in Power BI",
                "AI assistant",
                "Generative AI for building reports and summarising data.",
                ["Natural-language report creation", "Narrative summaries"],
            ),
        ],
        prices=[
            Price("Power BI Pro", "10", "2021-04-02", "2025-04-01"),
            Price("Power BI Pro", "14", "2025-04-01"),
            Price("Power BI Premium Per User", "20", "2021-04-02", "2025-04-01"),
            Price("Power BI Premium Per User", "24", "2025-04-01"),
        ],
        relationships=[
            ("OpenAI", "partner", "Copilot capabilities are built on OpenAI models via Azure OpenAI."),
            (
                "Databricks",
                "partner",
                "Azure Databricks is a first-party Azure service with native Power BI connectivity.",
            ),
        ],
        history=[
            HistoricEvent(
                "2023-11-15",
                "Microsoft Fabric becomes generally available",
                "Microsoft made Fabric, its unified analytics platform that includes Power BI, generally available "
                "at Ignite 2023, bundling data engineering, warehousing and BI on a single capacity model.",
                "product",
                [
                    "Microsoft Fabric reached general availability in November 2023",
                    "Power BI is delivered as part of Fabric",
                ],
                "https://www.microsoft.com/en-us/microsoft-fabric",
            ),
            HistoricEvent(
                "2025-04-01",
                "Power BI Pro rises from $10 to $14 and Premium Per User from $20 to $24",
                "Microsoft's first Power BI list-price increase since launch took effect on 1 April 2025: Pro moved "
                "from $10 to $14 per user per month and Premium Per User from $20 to $24.",
                "pricing",
                [
                    "Power BI Pro: $10 → $14 per user/month (+40%)",
                    "Premium Per User: $20 → $24 per user/month (+20%)",
                ],
                "https://www.microsoft.com/en-us/power-platform/products/power-bi/pricing",
            ),
        ],
    ),
    Rival(
        slug="tableau",
        name="Tableau",
        domain="tableau.com",
        aliases=["Tableau Software", "Salesforce Tableau"],
        tier=5,
        description="Visual analytics leader owned by Salesforce since 2019. Strong with analysts and "
        "data-literate teams; increasingly positioned around AI (Tableau Pulse, Tableau Agent) and Salesforce data.",
        segments=["Mid-market", "Enterprise"],
        ticker="CRM",
        cik="1108524",
        pricing_url="https://www.tableau.com/pricing/teams-orgs",
        news_query='"Tableau" analytics',
        products=[
            (
                "Tableau Cloud",
                "BI platform",
                "Fully hosted Tableau analytics platform.",
                ["Visual analytics", "Governance", "Tableau Pulse"],
            ),
            (
                "Tableau Server",
                "BI platform",
                "Self-managed Tableau deployment.",
                ["On-premises or private cloud", "Row-level security"],
            ),
            (
                "Tableau Desktop",
                "Authoring",
                "Desktop authoring for visual analysis.",
                ["Drag-and-drop visual analysis", "Calculated fields"],
            ),
            (
                "Tableau Pulse",
                "AI insights",
                "AI-generated metric insights delivered in the flow of work.",
                ["Metric digests", "Natural-language insights", "Slack and email delivery"],
            ),
        ],
        prices=[
            # Current published list prices; start date unknown, so they are dated when observed (seed time).
            Price("Creator", "75", "observed", features=["Tableau Desktop", "Full authoring"]),
            Price("Explorer", "42", "observed", features=["Web authoring on published data"]),
            Price("Viewer", "15", "observed", features=["View and interact with dashboards"]),
        ],
        relationships=[
            ("Salesforce", "acquirer", "Salesforce completed its acquisition of Tableau in August 2019."),
            ("Snowflake", "integration", "Native connector and joint customers in the cloud data stack."),
        ],
        history=[
            HistoricEvent(
                "2019-08-01",
                "Salesforce completes its acquisition of Tableau",
                "Salesforce closed its all-stock acquisition of Tableau, valued at about $15.7 billion, making "
                "Tableau part of the Salesforce platform.",
                "strategy",
                [
                    "Salesforce acquired Tableau in an all-stock deal valued at about $15.7B",
                    "The acquisition closed in August 2019",
                ],
                "https://www.tableau.com",
            ),
            HistoricEvent(
                "2024-02-01",
                "Tableau Pulse becomes generally available",
                "Tableau released Tableau Pulse, which uses generative AI to deliver personalised metric insights "
                "to business users in Slack, email and mobile.",
                "product",
                [
                    "Tableau Pulse became generally available in early 2024",
                    "Pulse delivers AI-generated metric insights",
                ],
                "https://www.tableau.com/products/tableau-pulse",
            ),
        ],
    ),
    Rival(
        slug="looker",
        name="Looker",
        domain="cloud.google.com",
        aliases=["Looker Studio", "Google Looker"],
        tier=4,
        description="Google Cloud's BI platform built around the LookML semantic layer, plus the free Looker "
        "Studio. Strongest in BigQuery-centric and data-team-led organisations.",
        segments=["Mid-market", "Enterprise"],
        ticker="GOOGL",
        cik=None,
        pricing_url="https://cloud.google.com/looker/pricing",
        news_query='"Looker" Google Cloud BI',
        products=[
            (
                "Looker",
                "BI platform",
                "Enterprise BI with a governed semantic model (LookML).",
                ["LookML semantic layer", "Embedded analytics", "Governed metrics"],
            ),
            (
                "Looker Studio",
                "Self-service BI",
                "Free self-service reporting (formerly Google Data Studio).",
                ["Free dashboards", "Google connectors", "Sharing"],
            ),
            (
                "Looker Studio Pro",
                "Self-service BI",
                "Paid tier of Looker Studio for teams.",
                ["Team workspaces", "Asset management", "Support"],
            ),
        ],
        prices=[
            Price("Looker Studio", "0", "2022-10-11", features=["Free self-service reporting"]),
        ],
        relationships=[
            ("Google", "acquirer", "Google completed its acquisition of Looker in February 2020."),
        ],
        history=[
            HistoricEvent(
                "2020-02-13",
                "Google completes its acquisition of Looker",
                "Google closed its $2.6 billion acquisition of Looker, folding it into Google Cloud.",
                "strategy",
                ["Google acquired Looker for $2.6B", "The deal closed in February 2020"],
                "https://cloud.google.com/looker",
            ),
            HistoricEvent(
                "2022-10-11",
                "Google Data Studio is rebranded as Looker Studio",
                "Google renamed Data Studio to Looker Studio, consolidating its BI products under the Looker brand.",
                "positioning",
                ["Data Studio was renamed Looker Studio in October 2022"],
                "https://lookerstudio.google.com",
            ),
        ],
    ),
    Rival(
        slug="qlik",
        name="Qlik",
        domain="qlik.com",
        aliases=["Qlik Sense", "Qlik Cloud"],
        tier=3,
        description="Private (Thoma Bravo-owned) analytics and data-integration vendor. Combines Qlik Sense "
        "analytics with Talend data integration; strong in manufacturing and European enterprises.",
        segments=["Mid-market", "Enterprise"],
        ticker=None,
        cik=None,
        pricing_url="https://www.qlik.com/us/pricing",
        news_query='"Qlik" analytics',
        products=[
            (
                "Qlik Cloud Analytics",
                "BI platform",
                "SaaS analytics built on Qlik's associative engine.",
                ["Associative engine", "Automations", "AI insights"],
            ),
            (
                "Qlik Sense",
                "BI platform",
                "Qlik's analytics product for cloud and client-managed deployments.",
                ["Self-service visualisation", "Associative exploration"],
            ),
            (
                "Qlik Talend Cloud",
                "Data integration",
                "Data integration and quality from the Talend acquisition.",
                ["Data pipelines", "Data quality", "Change data capture"],
            ),
        ],
        prices=[],
        relationships=[
            ("Thoma Bravo", "investor", "Private equity owner since taking Qlik private in 2016."),
            ("Talend", "acquired", "Qlik completed its acquisition of Talend in 2023."),
        ],
        history=[
            HistoricEvent(
                "2023-05-01",
                "Qlik completes its acquisition of Talend",
                "Qlik closed its acquisition of data-integration vendor Talend, expanding from analytics into "
                "data integration and quality.",
                "strategy",
                ["Qlik acquired Talend in 2023", "Adds data integration and data quality to Qlik"],
                "https://www.qlik.com",
            ),
        ],
    ),
    Rival(
        slug="thoughtspot",
        name="ThoughtSpot",
        domain="thoughtspot.com",
        aliases=["Mode"],
        tier=3,
        description="Search- and AI-driven analytics vendor that owns Mode for code-first analysis. "
        "Pitches natural-language 'ask your data' experiences and embedded analytics.",
        segments=["Mid-market", "Enterprise"],
        ticker=None,
        cik=None,
        pricing_url="https://www.thoughtspot.com/pricing",
        news_query='"ThoughtSpot"',
        products=[
            (
                "ThoughtSpot Analytics",
                "BI platform",
                "Search- and AI-driven self-service analytics.",
                ["Natural-language search", "Liveboards", "AI-generated insights"],
            ),
            (
                "ThoughtSpot Embedded",
                "Embedded analytics",
                "Analytics embedded in customers' own products.",
                ["Embedding SDK", "Multi-tenancy"],
            ),
            (
                "Mode",
                "Code-first analytics",
                "SQL, Python and R notebooks for data teams.",
                ["SQL editor", "Python and R notebooks", "Reports"],
            ),
        ],
        prices=[],
        relationships=[
            ("Mode Analytics", "acquired", "ThoughtSpot acquired Mode in 2023."),
            ("Snowflake", "integration", "Live query on Snowflake and joint go-to-market."),
        ],
        history=[
            HistoricEvent(
                "2023-06-20",
                "ThoughtSpot acquires Mode Analytics",
                "ThoughtSpot agreed to acquire Mode Analytics, adding code-first SQL, Python and R analysis to its "
                "search-driven platform.",
                "strategy",
                ["ThoughtSpot acquired Mode Analytics in June 2023", "Reported value about $200M"],
                "https://www.thoughtspot.com",
            ),
        ],
    ),
    Rival(
        slug="domo",
        name="Domo",
        domain="domo.com",
        aliases=[],
        tier=2,
        description="Publicly listed cloud BI and data-apps platform with consumption-based pricing; "
        "popular with executives and multi-location businesses.",
        segments=["SMB", "Mid-market"],
        ticker="DOMO",
        cik=None,
        pricing_url=None,  # domo.com answers automated requests with HTTP 405; no published list prices
        news_query='"Domo" BI',
        products=[
            (
                "Domo Platform",
                "BI platform",
                "Cloud BI with connectors, ETL and dashboards.",
                ["1,000+ connectors", "Magic ETL", "Dashboards"],
            ),
            ("Domo App Studio", "Data apps", "Build custom data apps on Domo.", ["Low-code app builder"]),
        ],
        prices=[],
        relationships=[],
        history=[
            HistoricEvent(
                "2018-06-29",
                "Domo lists on Nasdaq under the ticker DOMO",
                "Domo completed its initial public offering and began trading on the Nasdaq.",
                "financial",
                ["Domo IPO in June 2018", "Trades on Nasdaq as DOMO"],
                "https://www.domo.com",
            ),
        ],
    ),
]

USERS = [
    ("admin", "admin@northwind.example.com", "Ada Admin"),
    ("executive", "ceo@northwind.example.com", "Evan Exec"),
    ("product", "pm@northwind.example.com", "Priya Product"),
    ("sales", "sales@northwind.example.com", "Sam Sales"),
    ("marketing", "marketing@northwind.example.com", "Maya Marketing"),
    ("pricing", "pricing@northwind.example.com", "Pat Pricing"),
]


async def _ensure_org(db) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.slug == "northwind"))
    ).scalar_one_or_none()
    if org is None:
        org = Organization(name="Northwind Analytics", slug="northwind", brief_hour_utc=7, settings={})
        db.add(org)
        await db.flush()
        for role, email, name in USERS:
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
    # Reliability tiers: SimWire is simulated -> lowest trust.
    org.settings = {**(org.settings or {}), "domain_tiers": {"simwire.localtest.me": 4, "localtest.me": 4}}
    return org


async def _company(db, org_id: uuid.UUID) -> None:
    await db.execute(delete(CompanyProfile).where(CompanyProfile.org_id == org_id))
    await db.execute(delete(OwnPricePoint).where(OwnPricePoint.org_id == org_id))
    await db.execute(delete(OwnProduct).where(OwnProduct.org_id == org_id))
    await db.execute(delete(CustomerSegment).where(CustomerSegment.org_id == org_id))
    db.add(
        CompanyProfile(
            org_id=org_id,
            name="Northwind Analytics",
            website="https://northwind.example.com",
            description="Fictional mid-market BI vendor used for this demo: self-serve dashboards, AI summaries "
            "and embedded analytics for business teams.",
            positioning="The fastest way for mid-market business teams to get trustworthy answers — without a "
            "data team or a Microsoft/Salesforce lock-in.",
            differentiators=[
                "Transparent flat per-user pricing",
                "AI-assisted insights included in every plan",
                "Best-in-class onboarding",
                "Vendor-neutral connectors",
            ],
            target_markets=["Mid-market SaaS", "Retail", "Fintech"],
        )
    )
    insights = OwnProduct(
        org_id=org_id,
        name="Northwind Insights",
        category="BI platform",
        description="Dashboards, reports and AI summaries for business teams.",
        features=["Dashboards", "Hourly refresh", "SSO", "AI summaries", "API access"],
    )
    embed = OwnProduct(
        org_id=org_id,
        name="Northwind Embed",
        category="Embedded analytics",
        description="Embed Northwind dashboards inside your own SaaS product.",
        features=["White-labelling", "Row-level security", "React SDK"],
    )
    db.add_all([insights, embed])
    await db.flush()
    for plan, price in [("Starter", "12"), ("Pro", "24"), ("Enterprise", None)]:
        db.add(
            OwnPricePoint(
                org_id=org_id, product_id=insights.id, plan=plan, price=Decimal(price) if price else None
            )
        )
    db.add(OwnPricePoint(org_id=org_id, product_id=embed.id, plan="Embed Pro", price=Decimal("149")))
    for name, desc, share in [
        ("SMB", "Teams under 100 employees", 0.30),
        ("Mid-market", "100-2,000 employees — our core segment", 0.50),
        ("Enterprise", "2,000+ employees", 0.20),
    ]:
        db.add(CustomerSegment(org_id=org_id, name=name, description=desc, revenue_share=share))


async def _impact_for(company_ctx: dict, rival: Rival, ev: HistoricEvent) -> ImpactAnalysis:
    return await get_llm().complete(
        "impact",
        ImpactAnalysis,
        {
            **company_ctx,
            "competitor": rival.name,
            "threat_tier": rival.tier,
            "competitor_profile": rival.description,
            "recent_history": [],
            "title": ev.title,
            "summary": ev.summary,
            "category": ev.category,
            "significance": 0.7,
            "key_facts": ev.facts,
            "confidence_level": "confirmed",
            "verified_claims": ev.facts,
            "pricing_changes": [],
        },
    )


async def seed_market(replace: bool = False, with_impact: bool = True) -> dict:
    async with system_session() as db:
        org = await _ensure_org(db)
        org_id = org.id
        existing = (await db.execute(select(Competitor).where(Competitor.org_id == org_id))).scalars().all()
        if existing and not replace:
            return {
                "skipped": True,
                "reason": "org already has competitors; pass --replace to swap in the BI market",
            }
        if replace:
            # Competitor deletes cascade to sources, snapshots, events, evidence, pricing, products, KB chunks.
            await db.execute(delete(Competitor).where(Competitor.org_id == org_id))
            await db.execute(delete(Brief).where(Brief.org_id == org_id))
            await db.execute(delete(AgentRun).where(AgentRun.org_id == org_id))
            await db.execute(delete(KBChunk).where(KBChunk.org_id == org_id))
        await _company(db, org_id)
        await db.commit()

    company_ctx = {
        "company": {
            "name": "Northwind Analytics",
            "description": "Mid-market self-serve BI with AI summaries and embedded analytics.",
            "positioning": "Fast, trustworthy answers without lock-in.",
            "differentiators": ["Transparent flat per-user pricing", "AI insights in every plan"],
        },
        "own_products": [
            {"name": "Northwind Insights", "category": "BI platform", "description": "Dashboards"},
            {"name": "Northwind Embed", "category": "Embedded analytics", "description": "Embedding"},
        ],
        "own_prices": [
            {"plan": "Starter", "price": 12, "currency": "USD", "period": "month"},
            {"plan": "Pro", "price": 24, "currency": "USD", "period": "month"},
        ],
        "segments": [{"name": "Mid-market", "description": "core", "revenue_share": 0.5}],
    }
    counts = {
        "competitors": 0,
        "products": 0,
        "price_points": 0,
        "relationships": 0,
        "events": 0,
        "sources": 0,
    }

    for rival in RIVALS:
        async with system_session() as db:
            comp = Competitor(
                org_id=org_id,
                name=rival.name,
                domain=rival.domain,
                threat_tier=rival.tier,
                description=rival.description,
                segments=rival.segments,
                aliases=rival.aliases,
                ticker=rival.ticker,
                cik=rival.cik,
                summary=rival.description,
            )
            db.add(comp)
            await db.flush()
            counts["competitors"] += 1

            for name, category, desc, features in rival.products:
                prod = CompetitorProduct(
                    org_id=org_id, competitor_id=comp.id, name=name, category=category, description=desc
                )
                db.add(prod)
                await db.flush()
                db.add_all([ProductFeature(org_id=org_id, product_id=prod.id, name=f) for f in features])
                counts["products"] += 1

            for p in rival.prices:
                db.add(
                    PricePoint(
                        org_id=org_id,
                        competitor_id=comp.id,
                        plan=p.plan,
                        price=Decimal(p.price) if p.price is not None else None,
                        period=p.period,
                        features=p.features,
                        valid_from=d(p.valid_from),
                        valid_to=d(p.valid_to) if p.valid_to else None,
                    )
                )
                counts["price_points"] += 1

            for counterparty, rel_type, desc in rival.relationships:
                db.add(
                    CompetitorRelationship(
                        org_id=org_id,
                        competitor_id=comp.id,
                        counterparty_name=counterparty,
                        rel_type=rel_type,
                        description=desc,
                    )
                )
                counts["relationships"] += 1

            # Sources: real monitoring + the clearly-labelled SimWire feed.
            sources = [
                Source(
                    org_id=org_id,
                    competitor_id=comp.id,
                    name="News (GDELT)",
                    source_type="news",
                    url=gdelt_url(rival.news_query),
                    check_interval_minutes=720,
                    significance_threshold=0.6,
                    config={"query": rival.news_query},
                ),
                Source(
                    org_id=org_id,
                    competitor_id=comp.id,
                    name="SimWire (simulated)",
                    source_type="news",
                    url=f"{SIMWIRE}/{rival.slug}.xml",
                    check_interval_minutes=30,
                    config={"simulated": True},
                ),
            ]
            if rival.pricing_url:
                sources.append(
                    Source(
                        org_id=org_id,
                        competitor_id=comp.id,
                        name="Pricing page",
                        source_type="pricing",
                        url=rival.pricing_url,
                        check_interval_minutes=1440,
                        render_js=True,
                    )
                )
            if rival.cik:
                sources.append(
                    Source(
                        org_id=org_id,
                        competitor_id=comp.id,
                        name="SEC filings",
                        source_type="sec_filing",
                        url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={rival.cik}",
                        check_interval_minutes=1440,
                        config={"cik": rival.cik},
                    )
                )
            db.add_all(sources)
            counts["sources"] += len(sources)

            chunks = [
                {
                    "kind": "profile",
                    "ref_id": comp.id,
                    "competitor_id": comp.id,
                    "title": f"{rival.name} profile",
                    "content": f"{rival.description}\nProducts: "
                    + "; ".join(f"{n} — {desc}" for n, _, desc, _ in rival.products)
                    + "\nRelationships: "
                    + "; ".join(f"{c} ({t})" for c, t, _ in rival.relationships),
                }
            ]

            for ev in rival.history:
                event = Event(
                    org_id=org_id,
                    competitor_id=comp.id,
                    title=f"{rival.name}: {ev.title}",
                    summary=ev.summary,
                    category=ev.category,
                    key_facts=ev.facts,
                    confidence_level="confirmed",
                    confidence_score=0.95,
                    status="acknowledged",
                    stage="complete",
                    dedupe_key=f"record:{rival.slug}:{ev.date}",
                    detected_at=d(ev.date),
                    is_simulated=False,
                )
                db.add(event)
                await db.flush()
                db.add(
                    Evidence(
                        org_id=org_id,
                        event_id=event.id,
                        url=ev.reference,
                        domain=ev.reference.split("/")[2],
                        title=f"{rival.name} — public record",
                        snippet=ev.summary,
                        origin="record",
                        reliability_tier=1,
                        is_primary=True,
                        published_at=d(ev.date),
                        stances=[
                            {"claim_index": i, "stance": "supports", "rationale": "public record"}
                            for i in range(len(ev.facts))
                        ],
                    )
                )
                db.add(
                    Verification(
                        org_id=org_id,
                        event_id=event.id,
                        confidence_score=0.95,
                        level="confirmed",
                        rationale="Established public record, seeded as historical knowledge.",
                        claims=[
                            {
                                "claim": f,
                                "score": 0.95,
                                "supporting": 1,
                                "contradicting": 0,
                                "independent_domains": 1,
                                "has_primary": True,
                            }
                            for f in ev.facts
                        ],
                    )
                )
                analysis = await _impact_for(company_ctx, rival, ev) if with_impact else None
                severity = analysis.max_severity if analysis else 3
                pr = prioritize(
                    max_severity=severity,
                    threat_tier=rival.tier,
                    category=ev.category,
                    confidence=0.95,
                    confidence_level="confirmed",
                    novelty=1.0,
                )
                event.priority, event.priority_score = pr.priority.value, pr.score
                event.priority_factors = pr.factors
                if analysis:
                    db.add(
                        ImpactAssessment(
                            org_id=org_id,
                            event_id=event.id,
                            summary=analysis.summary,
                            overall_severity=severity,
                            dimensions={
                                k: getattr(analysis, k).model_dump()
                                for k in ("products", "customers", "pricing", "competitive_position")
                            },
                            affected_products=analysis.affected_products,
                            affected_segments=analysis.affected_segments,
                            role_implications=analysis.role_implications.model_dump(),
                            recommended_actions=[a.model_dump() for a in analysis.recommended_actions],
                            priority_rationale=pr.explanation,
                        )
                    )
                chunks.append(
                    {
                        "kind": "event",
                        "ref_id": event.id,
                        "competitor_id": comp.id,
                        "title": event.title,
                        "content": f"{ev.summary}\nFacts: {'; '.join(ev.facts)}",
                        "occurred_at": d(ev.date),
                        "meta": {"category": ev.category, "record": True},
                    }
                )
                counts["events"] += 1

            await kb_service.add_chunks(db, org_id, chunks)
            await db.commit()

    return {**counts, "seeded_at": utcnow().isoformat()}
