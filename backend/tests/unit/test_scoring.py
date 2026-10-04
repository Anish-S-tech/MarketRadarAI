from datetime import UTC, datetime, timedelta

from app.agents.scoring import (
    EvidenceItem,
    aggregate_confidence,
    grounded_stance,
    is_own_domain,
    prioritize,
    registrable_domain,
    reliability_tier,
    score_claim,
)
from app.db.enums import ConfidenceLevel, Priority


def test_domains():
    assert registrable_domain("https://www.blog.acme.com/x") == "acme.com"
    assert registrable_domain("https://news.bbc.co.uk/a") == "bbc.co.uk"
    assert is_own_domain("https://blog.acme.com/post", "acme.com")
    assert not is_own_domain("https://notacme.com", "acme.com")
    assert is_own_domain("http://acme.localtest.me:8090/p", "acme.localtest.me")
    assert not is_own_domain("http://newswire.localtest.me:8090/p", "acme.localtest.me")


def test_reliability_tiers_and_overrides():
    assert reliability_tier("https://acme.com/pricing", "acme.com") == 1
    assert reliability_tier("https://www.sec.gov/Archives/x") == 1
    assert reliability_tier("https://www.reuters.com/tech") == 2
    assert reliability_tier("https://someblog.io/post") == 3
    assert reliability_tier("https://www.reddit.com/r/x") == 4
    # the competitor's own domain always wins over org overrides
    assert reliability_tier("https://acme.com/p", "acme.com", {"acme.com": 4}) == 1
    assert reliability_tier("https://someblog.io/post", "", {"someblog.io": 2}) == 2


def test_grounded_stance_requires_competitor_and_content():
    claim = "Acme raised the Growth plan price to $99"
    names = ["Acme"]
    assert (
        grounded_stance("supports", claim, "Acme's Growth plan now costs $99 after it raised prices", names)
        == "supports"
    )
    assert grounded_stance("supports", claim, "Globex Growth plan raised to $99", names) == "irrelevant"
    assert (
        grounded_stance("supports", claim, "Acme raised the Growth plan price to $79", names) == "irrelevant"
    )
    assert grounded_stance("irrelevant", claim, "anything", names) == "irrelevant"


def _ev(stance, tier=3, primary=False, domain="x.com", age_days=0):
    return EvidenceItem(
        domain=domain,
        tier=tier,
        is_primary=primary,
        stance=stance,
        published_at=datetime.now(UTC) - timedelta(days=age_days),
    )


def test_primary_source_alone_confirms():
    res = aggregate_confidence([score_claim("c", [_ev("supports", tier=1, primary=True, domain="acme.com")])])
    assert res.level == ConfidenceLevel.confirmed and res.score >= 0.75


def test_single_weak_source_is_unverified():
    res = aggregate_confidence([score_claim("c", [_ev("supports", tier=4, domain="reddit.com")])])
    assert res.level == ConfidenceLevel.unverified


def test_independent_sources_confirm_without_primary():
    evs = [
        _ev("supports", tier=2, domain="reuters.com"),
        _ev("supports", tier=2, domain="bloomberg.com"),
        _ev("supports", tier=3, domain="blog.io"),
    ]
    assert aggregate_confidence([score_claim("c", evs)]).level == ConfidenceLevel.confirmed


def test_contradictions_mark_disputed():
    evs = [_ev("supports", tier=2, domain="a.com"), _ev("contradicts", tier=2, domain="b.com")]
    assert aggregate_confidence([score_claim("c", evs)]).level == ConfidenceLevel.disputed


def test_stale_evidence_counts_less():
    fresh = score_claim("c", [_ev("supports", tier=2, domain="a.com")])
    stale = score_claim("c", [_ev("supports", tier=2, domain="a.com", age_days=200)])
    assert stale.score < fresh.score


def test_no_evidence():
    assert aggregate_confidence([]).level == ConfidenceLevel.unverified


def test_priority_thresholds():
    hi = prioritize(
        max_severity=5,
        threat_tier=5,
        category="pricing",
        confidence=1.0,
        confidence_level="confirmed",
        novelty=1,
    )
    assert hi.priority == Priority.critical
    assert "impact=" in hi.explanation
    lo = prioritize(
        max_severity=1,
        threat_tier=1,
        category="other",
        confidence=0.3,
        confidence_level="unverified",
        novelty=0.3,
    )
    assert lo.priority == Priority.low


def test_priority_guardrails():
    capped = prioritize(
        max_severity=5,
        threat_tier=5,
        category="pricing",
        confidence=0.4,
        confidence_level="disputed",
        novelty=1,
    )
    assert capped.priority == Priority.medium and "capped" in capped.explanation
    raised = prioritize(
        max_severity=5,
        threat_tier=1,
        category="positioning",
        confidence=0.8,
        confidence_level="confirmed",
        novelty=0.3,
    )
    assert raised.priority.rank >= Priority.high.rank


def test_critical_requires_confirmed_evidence():
    likely = prioritize(
        max_severity=5,
        threat_tier=5,
        category="pricing",
        confidence=0.6,
        confidence_level="likely",
        novelty=1,
    )
    assert likely.priority == Priority.high and "requires confirmed" in likely.explanation
    confirmed = prioritize(
        max_severity=5,
        threat_tier=5,
        category="pricing",
        confidence=0.95,
        confidence_level="confirmed",
        novelty=1,
    )
    assert confirmed.priority == Priority.critical
