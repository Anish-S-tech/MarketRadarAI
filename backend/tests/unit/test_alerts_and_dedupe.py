import uuid

from app.agents.nodes.research import _overlap, dedupe_key, signature
from app.alerts.router import render_alert_body, subscription_matches
from app.db.models import AlertSubscription, Event

CTX = {
    "priority": "high",
    "competitor": "Acme",
    "category": "pricing",
    "confidence_level": "confirmed",
    "confidence_score": 0.9,
    "summary": "Acme raised prices.",
    "key_facts": ["Growth $79 -> $99"],
    "pricing_changes": [
        {"type": "price_changed", "plan": "Growth", "old_price": 79, "new_price": 99, "pct_change": 25.3}
    ],
    "role_implications": {
        "sales": "Expect price objections to soften.",
        "pricing": "Room to raise Pro.",
        "executive": "Watch margins.",
    },
    "actions": [
        {"action": "Update battlecard", "owner_role": "sales", "urgency": "this_week"},
        {"action": "Model a Pro increase", "owner_role": "pricing", "urgency": "this_quarter"},
    ],
    "differentiators": ["Onboarding"],
    "evidence": [{"title": "Pricing", "url": "http://a", "domain": "a", "tier": 1, "primary": True}],
    "link": "http://app/events/1",
}


def test_role_specific_alert_bodies():
    sales = render_alert_body("sales", CTX)
    pricing = render_alert_body("pricing", CTX)
    marketing = render_alert_body("marketing", CTX)
    assert "Talking points" in sales and "Update battlecard" in sales and "Model a Pro" not in sales
    assert "Price moves" in pricing and "+25.3%" in pricing and "Model a Pro increase" in pricing
    assert "Price moves" not in marketing
    assert "Watch margins." in marketing  # no marketing implication -> executive fallback


def _event(priority="high", category="pricing", competitor_id=None):
    return Event(priority=priority, category=category, competitor_id=competitor_id or uuid.uuid4())


def test_subscription_matching():
    comp = uuid.uuid4()
    sub = AlertSubscription(
        is_active=True, min_priority="high", categories=["pricing"], competitor_ids=[str(comp)]
    )
    assert subscription_matches(sub, _event("critical", "pricing", comp))
    assert not subscription_matches(sub, _event("medium", "pricing", comp))
    assert not subscription_matches(sub, _event("high", "product", comp))
    assert not subscription_matches(sub, _event("high", "pricing"))
    everything = AlertSubscription(is_active=True, min_priority="low", categories=[], competitor_ids=[])
    assert subscription_matches(everything, _event("low", "other"))


def test_dedupe_signature_matches_same_story_across_sources():
    ct = {"acme", "insights"}
    page = signature("Acme Insights raised 'Growth' price from $79/month to $99/month (+25.3%)") - ct
    blog = signature("New Growth plan pricing: now $99 per month (previously $79)") - ct
    unrelated = signature("How Acme customers cut reporting time in half") - ct
    assert _overlap(page, blog) >= 0.6
    assert _overlap(page, unrelated) == 0


def test_dedupe_key_is_stable():
    cid = uuid.uuid4()
    assert dedupe_key(cid, "pricing", "Acme: Growth now $99!") == dedupe_key(
        cid, "pricing", "acme  growth now $99"
    )
