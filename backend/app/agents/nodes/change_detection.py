"""Change Detection Agent: separates meaningful changes (pricing, products, features, positioning,
partnerships, strategy) from noise, and classifies/scores each one."""

import re
import uuid
from typing import Any

from sqlalchemy import select

from app.agents.tracing import traced
from app.config import settings
from app.db.enums import FEED_SOURCE_TYPES, SourceType
from app.db.models import Change, Competitor, PricePoint, Snapshot, Source
from app.db.session import tenant_session
from app.knowledge import kb_service
from app.llm.client import get_llm
from app.llm.schemas import ChangeClassification, PricingTable
from app.monitoring.normalize import block_diff
from app.monitoring.pricing import compare_pricing

MAX_NEW_ITEMS = 10


def _num_variants(v: float | None) -> set[str]:
    if v is None:
        return set()
    return {f"{v:g}", f"{v:,.0f}", f"{v:.2f}", f"{v:,.2f}"}


def ground_pricing_changes(changes: list[dict], added: list[str], removed: list[str]) -> list[dict]:
    """Drop pricing 'changes' that are not visible in the textual diff (guards against LLM extraction
    variance between two runs producing phantom price moves)."""
    added_txt = "\n".join(added).lower()
    removed_txt = "\n".join(removed).lower()
    kept = []
    for c in changes:
        t = c["type"]
        if t == "price_changed":
            if c.get("new_price") is None or any(n in added_txt for n in _num_variants(c.get("new_price"))):
                kept.append(c)
        elif t == "plan_added":
            if c["plan"].lower() in added_txt:
                kept.append(c)
        elif t == "plan_removed":
            if c["plan"].lower() in removed_txt:
                kept.append(c)
        elif t in ("features_added", "features_removed"):
            hay = added_txt if t == "features_added" else removed_txt
            feats = [f for f in c["features"] if f.lower()[:40] in hay]
            if feats:
                kept.append({**c, "features": feats})
    return kept


def pricing_headline(changes: list[dict]) -> str:
    """Precise, deterministic headline for grounded pricing moves (small LLMs tend to write 'Pricing update')."""
    order = {
        "price_changed": 0,
        "plan_added": 1,
        "plan_removed": 2,
        "features_removed": 3,
        "features_added": 4,
    }
    lead = sorted(changes, key=lambda c: order.get(c["type"], 9))[0]
    text = lead["description"]
    more = len(changes) - 1
    return text + (f" (+{more} more pricing change{'s' if more > 1 else ''})" if more else "")


def _item_key(item: dict) -> str:
    return item.get("id") or item.get("url") or item.get("title", "")


async def _extract_pricing(competitor: str, text: str) -> dict:
    table = await get_llm().complete(
        "extract_pricing", PricingTable, {"competitor": competitor, "text": text}, tier="classify"
    )
    plans = [p.model_dump() for p in table.plans if is_plausible_plan_name(p.name)]
    return {"plans": plans}


# Words that small models sometimes promote to "plans" from pricing-page chrome ("Custom", "Contact sales"...).
_NOT_PLAN_NAMES = {
    "custom",
    "custom pricing",
    "user",
    "users",
    "per user",
    "contact",
    "contact sales",
    "contact us",
    "pricing",
    "plan",
    "plans",
    "monthly",
    "annually",
    "annual",
    "yearly",
    "billed annually",
    "free trial",
    "get started",
    "compare plans",
    "features",
    "faq",
    "add-ons",
    "add ons",
}


def is_plausible_plan_name(name: str) -> bool:
    n = " ".join(name.lower().split())
    return len(n) >= 2 and n not in _NOT_PLAN_NAMES and not n.startswith(("$", "€", "£")) and len(n) <= 60


@traced("change_detection")
async def change_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    org_id = uuid.UUID(state["org_id"])
    llm = get_llm()
    async with tenant_session(org_id) as db:
        snap = await db.get(Snapshot, uuid.UUID(state["snapshot_id"]))
        prev = (
            await db.get(Snapshot, uuid.UUID(state["prev_snapshot_id"]))
            if state.get("prev_snapshot_id")
            else None
        )
        source = await db.get(Source, snap.source_id)  # type: ignore[union-attr]
        assert snap and source
        competitor = await db.get(Competitor, source.competitor_id)
        assert competitor
        st = SourceType(source.source_type)
        threshold = source.significance_threshold or settings.default_significance_threshold
        base_ctx = {
            "competitor": competitor.name,
            "source_name": source.name,
            "source_type": st.value,
            "url": source.url,
        }
        candidates: list[tuple[str, dict, ChangeClassification]] = []  # (kind, diff, classification)

        # ---------- baseline (first snapshot): record, learn, no alerts ----------
        if prev is None:
            if st == SourceType.pricing:
                pricing = await _extract_pricing(competitor.name, snap.text)
                snap.structured = {**snap.structured, "pricing": pricing}
                # Only seed pricing history from a baseline when none is known yet; curated history (e.g. from
                # an import) must not be overwritten by a first-pass extraction whose plan names may differ.
                has_history = (
                    await db.execute(
                        select(PricePoint.id).where(PricePoint.competitor_id == competitor.id).limit(1)
                    )
                ).first()
                if not has_history:
                    await kb_service.sync_price_points(
                        db,
                        org_id,
                        competitor.id,
                        pricing["plans"],
                        snapshot_id=snap.id,
                        observed_at=snap.fetched_at,
                    )
            if st not in FEED_SOURCE_TYPES:
                await kb_service.add_chunks(
                    db,
                    org_id,
                    [
                        {
                            "kind": "snapshot",
                            "ref_id": snap.id,
                            "competitor_id": competitor.id,
                            "title": f"{competitor.name} — {source.name}",
                            "content": snap.text[:6000],
                            "meta": {"url": source.url, "source_type": st.value},
                        }
                    ],
                )
            await db.commit()
            return {"changes": [], "_summary": {"baseline": True}}

        # ---------- feeds: each new item is a candidate ----------
        if st in FEED_SOURCE_TYPES:
            seen = {_item_key(i) for i in prev.structured.get("items", [])}
            new_items = [i for i in snap.structured.get("items", []) if _item_key(i) not in seen][
                :MAX_NEW_ITEMS
            ]
            for item in new_items:
                cls = await llm.complete(
                    "classify_change",
                    ChangeClassification,
                    {
                        **base_ctx,
                        "item_title": item["title"],
                        "item_summary": item.get("summary", ""),
                        "added": [],
                        "removed": [],
                        "pricing_changes": [],
                    },
                    tier="classify",
                )
                candidates.append(("new_item", {"item": item}, cls))

        # ---------- pages: text diff (+ structured pricing diff) ----------
        else:
            diff = block_diff(prev.text, snap.text)
            pricing_changes: list[dict] = []
            if st == SourceType.pricing:
                pricing = await _extract_pricing(competitor.name, snap.text)
                snap.structured = {**snap.structured, "pricing": pricing}
                old_pricing = prev.structured.get("pricing")
                if old_pricing is None:
                    old_pricing = await _extract_pricing(competitor.name, prev.text)
                raw_changes = compare_pricing(old_pricing, pricing, competitor.name)
                pricing_changes = ground_pricing_changes(raw_changes, diff["added"], diff["removed"])
            if diff["added"] or diff["removed"] or pricing_changes:
                cls = await llm.complete(
                    "classify_change",
                    ChangeClassification,
                    {
                        **base_ctx,
                        "added": diff["added"],
                        "removed": diff["removed"],
                        "pricing_changes": pricing_changes,
                    },
                    tier="classify",
                )
                if pricing_changes:
                    # Structured, grounded price moves are meaningful regardless of the LLM's opinion.
                    cls.is_meaningful = True
                    cls.category = "pricing"  # type: ignore[assignment]
                    cls.significance = max(cls.significance, 0.7)
                    facts = [pc["description"] for pc in pricing_changes]
                    cls.key_facts = facts + [f for f in cls.key_facts if f not in facts]
                    cls.title = pricing_headline(pricing_changes)
                candidates.append(
                    (
                        "pricing" if pricing_changes else "diff",
                        {
                            "added": diff["added"][:200],
                            "removed": diff["removed"][:200],
                            "pricing_changes": pricing_changes,
                        },
                        cls,
                    )
                )

        results = []
        for kind, diff_payload, cls in candidates:
            significant = cls.is_meaningful and cls.significance >= threshold
            # A feed item's own headline is authoritative; the LLM's paraphrase can drift (it once turned
            # "Google bundles Looker Studio Pro with Workspace" into "Google Partners with Looker").
            headline = diff_payload.get("item", {}).get("title") if kind == "new_item" else None
            base_title = headline or cls.title
            title = (
                base_title
                if competitor.name.lower() in base_title.lower()
                else f"{competitor.name}: {base_title}"
            )
            change = Change(
                org_id=org_id,
                source_id=source.id,
                competitor_id=competitor.id,
                prev_snapshot_id=prev.id,
                snapshot_id=snap.id,
                kind=kind,
                diff=diff_payload,
                category=cls.category,
                significance=cls.significance,
                title=re.sub(r"\s+", " ", title)[:500],
                summary=cls.summary,
                key_facts=cls.key_facts[:10],
                is_significant=significant,
            )
            db.add(change)
            await db.flush()
            results.append(
                {
                    "change_id": str(change.id),
                    "category": cls.category,
                    "significance": cls.significance,
                    "is_significant": significant,
                    "title": change.title,
                }
            )
        await db.commit()

    return {
        "changes": results,
        "_summary": {
            "candidates": len(results),
            "significant": sum(r["is_significant"] for r in results),
            "threshold": threshold,
            "changes": results,
        },
    }
