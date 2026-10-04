"""Deterministic fallbacks for every LLM task.

Used when the LLM is unreachable or keeps returning invalid output (graceful degradation), and as the
`fake` provider in tests/offline demos. They are intentionally simple but produce valid, useful output.
"""

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.llm.schemas import (
    BriefSummary,
    ChangeClassification,
    ClaimJudgment,
    CompetitorSummary,
    DimensionImpact,
    EntityExtraction,
    EvidenceJudgment,
    ExtractedProduct,
    ExtractedRelationship,
    ImpactAnalysis,
    PricingPlan,
    PricingTable,
    RecommendedAction,
    ResearchPlan,
    RoleImplications,
)

CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("pricing", ["price", "pricing", "$", "per month", "/mo", "per user", "discount", "free tier", "plan"]),
    ("partnership", ["partner", "partnership", "alliance", "integration with", "teams up", "collaborat"]),
    (
        "financial",
        ["revenue", "earnings", "quarter", "10-q", "10-k", "8-k", "raises", "funding", "ipo", "guidance"],
    ),
    ("leadership", ["ceo", "cto", "cfo", "appoints", "hires", "steps down", "chief"]),
    ("strategy", ["acquire", "acquisition", "merger", "expands into", "layoff", "restructur", "enters"]),
    (
        "product",
        ["launch", "introduc", "new product", "general availability", "now available", "beta", "release"],
    ),
    ("feature", ["feature", "support for", "adds", "improved", "integration", "api", "sso"]),
    ("positioning", ["leading", "platform for", "trusted by", "the only", "mission", "why us"]),
]

HIGH_SIGNAL = [
    "acquire",
    "acquisition",
    "price increase",
    "price cut",
    "launch",
    "partnership",
    "layoff",
    "raises",
    "funding",
    "ceo",
    "discontinu",
    "free tier",
    "general availability",
]

STOP = set(
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
        "this",
        "that",
        "it",
        "its",
        "at",
        "as",
        "from",
        "new",
        "our",
        "we",
    ]
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9$.%]+", text.lower()) if t not in STOP and len(t) > 1}


def classify_change(ctx: dict[str, Any]) -> ChangeClassification:
    added: list[str] = ctx.get("added") or []
    removed: list[str] = ctx.get("removed") or []
    pricing_changes: list[dict] = ctx.get("pricing_changes") or []
    item_title = ctx.get("item_title") or ""
    text = " ".join([item_title, *added, *removed]).lower()
    competitor = ctx.get("competitor", "Competitor")

    category = "other"
    for cat, kws in CATEGORY_KEYWORDS:
        if any(k in text for k in kws):
            category = cat
            break
    if pricing_changes:
        category = "pricing"

    changed_chars = sum(len(x) for x in added) + sum(len(x) for x in removed)
    significance = min(0.6, changed_chars / 2000)
    significance += 0.25 * sum(1 for k in HIGH_SIGNAL if k in text) / 2
    if pricing_changes:
        significance = max(significance, 0.75)
    if item_title:
        significance = max(significance, 0.5)
    significance = min(1.0, significance)

    facts = [pc["description"] for pc in pricing_changes][:5] or [a[:200] for a in added[:3]]
    headline_src = item_title or (facts[0] if facts else (added[0] if added else "content updated"))
    return ChangeClassification(
        is_meaningful=changed_chars > 40 or bool(pricing_changes) or bool(item_title),
        category=category,
        significance=round(significance, 2),
        title=f"{competitor}: {headline_src[:110]}",
        summary=" ".join(facts)[:600]
        or f"{competitor} updated {ctx.get('source_name', 'a monitored page')}.",
        key_facts=facts,
    )


PRICE_RE = re.compile(
    r"(?P<cur>[$€£])\s?(?P<amt>\d[\d,]*(?:\.\d{1,2})?)\s*(?:/|per\s+)?\s*(?P<per>user\s*/\s*month|month|mo|year|yr|annum|user)?",
    re.I,
)
CUSTOM_RE = re.compile(r"contact sales|custom pricing|let's talk|get a quote", re.I)
CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}


def extract_pricing(ctx: dict[str, Any]) -> PricingTable:
    lines = [ln.strip() for ln in (ctx.get("text") or "").splitlines() if ln.strip()]
    plans: list[PricingPlan] = []
    current: PricingPlan | None = None
    pending_name: str | None = None
    for ln in lines:
        m = PRICE_RE.search(ln)
        is_heading = len(ln) <= 40 and not m and not ln.startswith(("-", "•", "*")) and ln[:1].isupper()
        if m and pending_name:
            per = (m.group("per") or "month").lower()
            period = "year" if per.startswith(("y", "an")) else "month"
            current = PricingPlan(
                name=pending_name,
                price=float(m.group("amt").replace(",", "")),
                currency=CURRENCY.get(m.group("cur"), "USD"),
                period=period,
            )
            plans.append(current)
            pending_name = None
        elif CUSTOM_RE.search(ln) and pending_name:
            current = PricingPlan(name=pending_name, price=None)
            plans.append(current)
            pending_name = None
        elif is_heading:
            pending_name = ln
        elif current is not None and ln.startswith(("-", "•", "*", "✓")):
            current.features.append(ln.lstrip("-•*✓ ").strip())
    return PricingTable(plans=plans)


def research_plan(ctx: dict[str, Any]) -> ResearchPlan:
    facts = ctx.get("key_facts") or []
    claims = [f for f in facts if f][:3] or [ctx.get("summary") or ctx.get("title", "")]
    competitor = ctx.get("competitor", "")
    title = re.sub(rf"^{re.escape(competitor)}:\s*", "", ctx.get("title", ""))
    queries = [f"{competitor} {title}"[:120], f"{competitor} {ctx.get('category', '')} news"]
    return ResearchPlan(claims=claims, queries=queries)


def judge_evidence(ctx: dict[str, Any]) -> EvidenceJudgment:
    ev = _tokens(ctx.get("evidence_text", ""))
    judgments = []
    for i, claim in enumerate(ctx.get("claims") or []):
        ct = _tokens(claim)
        if not ct:
            continue
        overlap = len(ct & ev) / len(ct)
        nums = {t for t in ct if re.search(r"\d", t)}
        num_hit = not nums or bool(nums & ev)
        stance = "supports" if overlap >= 0.5 and num_hit else "irrelevant"
        judgments.append(
            ClaimJudgment(claim_index=i, stance=stance, rationale=f"token overlap {overlap:.2f}")
        )
    return EvidenceJudgment(judgments=judgments)


REL_PATTERNS = [
    (r"partner(?:ship|s|ed)? with ([A-Z][\w&.\- ]{1,40})", "partner"),
    (r"integrat(?:ion|es|ed) with ([A-Z][\w&.\- ]{1,40})", "integration"),
    (r"acquir(?:es|ed|e) ([A-Z][\w&.\- ]{1,40})", "acquired"),
    (r"acquired by ([A-Z][\w&.\- ]{1,40})", "acquirer"),
    (r"(?:led|backed) by ([A-Z][\w&.\- ]{1,40})", "investor"),
]
PRODUCT_PATTERNS = [
    r"(?:launch(?:es|ed)?|introduc(?:es|ed|ing)|announc(?:es|ed|ing)) ([A-Z][\w\-]*(?: [A-Z0-9][\w\-]*){0,3})"
]


def extract_entities(ctx: dict[str, Any]) -> EntityExtraction:
    text = ctx.get("text", "")
    rels, prods = [], []
    seen: set[str] = set()
    for pat, rt in REL_PATTERNS:
        for m in re.finditer(pat, text):
            name = m.group(1).strip(" .,")
            key = f"{rt}:{name.lower()}"
            if key not in seen and name.lower() != ctx.get("competitor", "").lower():
                seen.add(key)
                rels.append(ExtractedRelationship(counterparty=name, rel_type=rt))
    for pat in PRODUCT_PATTERNS:
        for m in re.finditer(pat, text):
            name = m.group(1).strip(" .,")
            if name.lower() not in seen and len(name) > 2:
                seen.add(name.lower())
                prods.append(ExtractedProduct(name=name, description=text[m.start() : m.start() + 200]))
    return EntityExtraction(products=prods[:5], relationships=rels[:5])


CATEGORY_BASE_SEVERITY = {
    "pricing": 4,
    "strategy": 4,
    "product": 3,
    "partnership": 3,
    "financial": 3,
    "feature": 2,
    "leadership": 2,
    "positioning": 2,
    "other": 1,
}


def impact(ctx: dict[str, Any]) -> ImpactAnalysis:
    cat = ctx.get("category", "other")
    base = CATEGORY_BASE_SEVERITY.get(cat, 2)
    tier = int(ctx.get("threat_tier", 3))
    sig = float(ctx.get("significance", 0.5))
    sev = max(1, min(5, round(base * (0.6 + 0.4 * sig) + (tier - 3) * 0.5)))
    comp = ctx.get("competitor", "The competitor")
    title = ctx.get("title", "")
    own_products = [p["name"] for p in ctx.get("own_products", [])][:3]

    def dim(offset: int, why: str) -> DimensionImpact:
        return DimensionImpact(severity=max(1, min(5, sev + offset)), rationale=why)

    return ImpactAnalysis(
        summary=f"{title}. Estimated impact severity {sev}/5 given a {cat} change by a tier-{tier} competitor.",
        products=dim(
            0 if cat in {"product", "feature"} else -1, f"{cat} change may shift feature expectations"
        ),
        customers=dim(-1, "Customers comparing vendors may re-evaluate"),
        pricing=dim(
            0 if cat == "pricing" else -2,
            "Direct price comparison pressure" if cat == "pricing" else "Indirect",
        ),
        competitive_position=dim(0, f"{comp} strengthens its position in overlapping segments"),
        affected_products=own_products,
        affected_segments=[s["name"] for s in ctx.get("segments", [])][:2],
        role_implications=RoleImplications(
            executive=f"Monitor {comp}'s move; assess strategic response.",
            product=f"Review roadmap parity against {comp}'s change.",
            sales=f"Prepare talking points for deals where {comp} is in the running.",
            marketing=f"Consider updating comparison pages and messaging vs {comp}.",
            pricing=f"Re-check price positioning vs {comp}."
            if cat == "pricing"
            else "No direct pricing action.",
        ),
        recommended_actions=[
            RecommendedAction(
                action=f"Update the {comp} battlecard", owner_role="sales", urgency="this_week"
            ),
            RecommendedAction(
                action="Review competitive positioning", owner_role="marketing", urgency="this_week"
            ),
        ],
    )


def brief_summary(ctx: dict[str, Any]) -> BriefSummary:
    events = ctx.get("events", [])
    if not events:
        return BriefSummary(
            headline="Quiet day — no significant competitor moves detected",
            executive_summary="No new high-signal competitive events in the last 24 hours.",
        )
    top = events[:5]
    comps = sorted({e["competitor"] for e in events})
    return BriefSummary(
        headline=f"{len(events)} competitive developments across {len(comps)} competitors",
        executive_summary=" ".join(f"[{e['priority'].upper()}] {e['title']}." for e in top),
        key_themes=sorted({e["category"] for e in events}),
        watch_list=[f"Follow up on: {e['title']}" for e in top if e["priority"] in ("high", "critical")][:3],
    )


def competitor_summary(ctx: dict[str, Any]) -> CompetitorSummary:
    recent = "; ".join(e["title"] for e in ctx.get("recent_events", [])[:5])
    return CompetitorSummary(summary=f"{ctx.get('description', '')} Recent activity: {recent}".strip())


FALLBACKS: dict[str, Callable[[dict[str, Any]], BaseModel]] = {
    "classify_change": classify_change,
    "extract_pricing": extract_pricing,
    "research_plan": research_plan,
    "judge_evidence": judge_evidence,
    "extract_entities": extract_entities,
    "impact": impact,
    "brief_summary": brief_summary,
    "competitor_summary": competitor_summary,
}
