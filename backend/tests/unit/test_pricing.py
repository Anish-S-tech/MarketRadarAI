from pathlib import Path

from app.agents.nodes.change_detection import ground_pricing_changes, pricing_headline
from app.llm.heuristics import extract_pricing
from app.monitoring.extract import extract_text
from app.monitoring.normalize import block_diff, normalize_text
from app.monitoring.pricing import compare_pricing

FIXTURE = Path(__file__).parent.parent / "fixtures" / "html" / "acme_pricing_v1.html"

OLD = {
    "plans": [
        {"name": "Starter", "price": 29, "period": "month", "features": ["5 dashboards"]},
        {"name": "Growth", "price": 79, "period": "month", "features": ["SSO"]},
        {"name": "Legacy", "price": 9, "period": "month", "features": []},
    ]
}
NEW = {
    "plans": [
        {"name": "Starter", "price": 29, "period": "month", "features": ["5 dashboards", "AI summaries"]},
        {"name": "growth", "price": 99, "period": "month", "features": ["SSO"]},
        {"name": "Enterprise", "price": None, "period": "month", "features": []},
    ]
}


def _page_text() -> str:
    return normalize_text(extract_text(FIXTURE.read_text(encoding="utf-8"), mode="full").text)


def test_compare_pricing_detects_all_change_types():
    changes = {(c["type"], c["plan"]) for c in compare_pricing(OLD, NEW, "Acme")}
    assert ("price_changed", "growth") in changes
    assert ("features_added", "Starter") in changes
    assert ("plan_added", "Enterprise") in changes
    assert ("plan_removed", "Legacy") in changes


def test_price_change_percentage_and_description():
    pc = next(c for c in compare_pricing(OLD, NEW, "Acme") if c["type"] == "price_changed")
    assert pc["pct_change"] == 25.3
    assert "raised" in pc["description"]
    assert "$79/month" in pc["description"] and "$99/month" in pc["description"]


def test_grounding_drops_phantom_changes():
    changes = compare_pricing(OLD, NEW, "Acme")
    # Only the Growth price and the Starter feature are visible in the text diff.
    grounded = ground_pricing_changes(
        changes, added=["Growth $99 / month", "✓ AI summaries"], removed=["Growth $79 / month"]
    )
    assert {c["type"] for c in grounded} == {"price_changed", "features_added"}


def test_pricing_headline_leads_with_price_move():
    title = pricing_headline(compare_pricing(OLD, NEW, "Acme"))
    assert title.startswith("Acme raised 'growth' price")
    assert "more pricing changes" in title


def test_heuristic_extracts_demo_pricing_page():
    table = extract_pricing({"text": _page_text()})
    by_name = {p.name: p for p in table.plans}
    assert by_name["Starter"].price == 29
    assert by_name["Growth"].price == 79
    assert by_name["Enterprise"].price is None
    assert "SSO" in by_name["Growth"].features


def test_diff_of_real_pages():
    v1 = _page_text()
    v2 = v1.replace("$79 / month", "$99 / month")
    assert block_diff(v1, v2) == {"added": ["$99 / month"], "removed": ["$79 / month"]}


def test_plan_name_filter_drops_page_chrome():
    from app.agents.nodes.change_detection import is_plausible_plan_name

    for good in ("Essentials", "Pro", "Power BI Premium Per User", "Enterprise", "Free"):
        assert is_plausible_plan_name(good)
    for junk in ("Custom", "User", "Contact sales", "$25", "", "Billed annually"):
        assert not is_plausible_plan_name(junk)
