"""Deterministic, auditable scoring: source reliability, evidence confidence and event priority.

LLMs judge *what* the evidence says; these functions decide *how much to trust it* and *how urgent it is*,
so every alert can be explained factor by factor.
"""

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.db.enums import ConfidenceLevel, Priority

TIER_WEIGHTS = {1: 1.0, 2: 0.75, 3: 0.45, 4: 0.2}

TIER1_DOMAINS = {"sec.gov", "data.sec.gov"}
TIER2_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "nytimes.com",
    "cnbc.com",
    "techcrunch.com",
    "theverge.com",
    "theinformation.com",
    "axios.com",
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
    "forbes.com",
    "venturebeat.com",
    "zdnet.com",
    "wired.com",
    "fortune.com",
}
TIER4_DOMAINS = {
    "reddit.com",
    "medium.com",
    "quora.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "facebook.com",
    "news.ycombinator.com",
    "pinterest.com",
    "tiktok.com",
}


def registrable_domain(url_or_host: str) -> str:
    host = urlparse(url_or_host).hostname if "//" in url_or_host else url_or_host
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) > 2 and parts[-2] in {"co", "com", "org", "net", "ac", "gov"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def host_domain(url: str) -> str:
    return ((urlparse(url).hostname if "//" in url else url) or "").lower().removeprefix("www.")


def is_own_domain(url: str, competitor_domain: str) -> bool:
    """True if the URL's host is the competitor's domain or one of its subdomains."""
    if not competitor_domain:
        return False
    host = (urlparse(url).hostname if "//" in url else url) or ""
    host = host.lower().removeprefix("www.")
    d = competitor_domain.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    d = d.split(":")[0].removeprefix("www.")
    return host == d or host.endswith("." + d)


def reliability_tier(url: str, competitor_domain: str = "", overrides: dict[str, int] | None = None) -> int:
    if is_own_domain(url, competitor_domain):
        return 1
    d = registrable_domain(url)
    host = host_domain(url)
    if overrides:
        for key in (host, d):
            if key in overrides:
                return int(overrides[key])
    if d in TIER1_DOMAINS:
        return 1
    if d in TIER2_DOMAINS:
        return 2
    if d in TIER4_DOMAINS:
        return 4
    return 3


_STOP = set(
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
        "has",
        "have",
        "new",
        "now",
        "plan",
        "plans",
        "per",
        "month",
    ]
)


def _sig_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9$%.']+", text.lower()) if t not in _STOP and len(t) > 2}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def grounded_stance(
    stance: str, claim: str, evidence_text: str, competitor_names: list[str], min_overlap: float = 0.3
) -> str:
    """Deterministic guard against over-eager LLM judgments: evidence can only support/contradict a claim
    about a competitor if it actually names the competitor and shares enough of the claim's content."""
    if stance not in ("supports", "contradicts"):
        return stance
    ev = evidence_text.lower()
    if not any(n and n.lower() in ev for n in competitor_names):
        return "irrelevant"
    ct = _sig_tokens(claim) - {t for n in competitor_names for t in _sig_tokens(n)}
    if ct and len(ct & _sig_tokens(evidence_text)) / len(ct) < min_overlap:
        return "irrelevant"
    if stance == "supports":
        nums = _numbers(claim)
        if nums and not nums & _numbers(evidence_text):
            return "irrelevant"
    return stance


@dataclass
class EvidenceItem:
    domain: str
    tier: int
    is_primary: bool
    stance: str  # supports | contradicts | irrelevant
    published_at: datetime | None = None


@dataclass
class ClaimScore:
    claim: str
    score: float
    supporting: int
    contradicting: int
    independent_domains: int
    has_primary: bool


@dataclass
class ConfidenceResult:
    score: float
    level: ConfidenceLevel
    claims: list[ClaimScore] = field(default_factory=list)
    rationale: str = ""


def _recency(published_at: datetime | None, now: datetime) -> float:
    if not published_at:
        return 0.9
    age_days = max(0.0, (now - published_at).total_seconds() / 86400)
    return 1.0 if age_days <= 14 else max(0.5, 1.0 - (age_days - 14) / 180)


def score_claim(claim: str, evidence: list[EvidenceItem], now: datetime | None = None) -> ClaimScore:
    now = now or datetime.now(UTC)
    s = c = 0.0
    sup_domains: set[str] = set()
    n_sup = n_con = 0
    has_primary = False
    for e in evidence:
        w = TIER_WEIGHTS.get(e.tier, 0.3) * (1.5 if e.is_primary else 1.0) * _recency(e.published_at, now)
        if e.stance == "supports":
            s += w
            n_sup += 1
            sup_domains.add(e.domain)
            has_primary = has_primary or e.is_primary
        elif e.stance == "contradicts":
            c += w
            n_con += 1
    if s + c == 0:
        return ClaimScore(claim, 0.15, 0, 0, 0, False)
    agreement = s / (s + c)
    strength = 1 - math.exp(-s)  # saturating: more (and better) support -> closer to 1
    diversity = min(0.15, 0.05 * max(0, len(sup_domains) - 1))
    primary_bonus = 0.1 if has_primary else 0.0
    score = max(0.0, min(1.0, agreement * strength + diversity + primary_bonus - (0.2 if c > s else 0.0)))
    return ClaimScore(claim, round(score, 3), n_sup, n_con, len(sup_domains), has_primary)


def aggregate_confidence(claim_scores: list[ClaimScore]) -> ConfidenceResult:
    if not claim_scores:
        return ConfidenceResult(0.2, ConfidenceLevel.unverified, [], "No checkable claims")
    # First claim is the headline claim -> double weight.
    weights = [2.0] + [1.0] * (len(claim_scores) - 1)
    score = sum(w * cs.score for w, cs in zip(weights, claim_scores, strict=True)) / sum(weights)
    head = claim_scores[0]
    total_con = sum(cs.contradicting for cs in claim_scores)
    total_sup = sum(cs.supporting for cs in claim_scores)
    if total_con and total_con * 2 >= total_sup:
        level = ConfidenceLevel.disputed
    elif score >= 0.75 and (head.has_primary or head.independent_domains >= 2):
        level = ConfidenceLevel.confirmed
    elif score >= 0.5:
        level = ConfidenceLevel.likely
    else:
        level = ConfidenceLevel.unverified
    rationale = (
        f"{total_sup} supporting / {total_con} contradicting judgments across {len(claim_scores)} claims; "
        f"headline claim backed by {head.independent_domains} independent domain(s)"
        + (" incl. the competitor's own primary source" if head.has_primary else "")
    )
    return ConfidenceResult(round(score, 3), level, claim_scores, rationale)


CATEGORY_WEIGHTS = {
    "pricing": 1.0,
    "strategy": 0.9,
    "product": 0.8,
    "partnership": 0.8,
    "financial": 0.7,
    "leadership": 0.6,
    "feature": 0.6,
    "positioning": 0.5,
    "other": 0.3,
}
PRIORITY_THRESHOLDS = [(0.72, Priority.critical), (0.55, Priority.high), (0.35, Priority.medium)]
FACTOR_WEIGHTS = {"impact": 0.35, "threat": 0.2, "category": 0.15, "confidence": 0.2, "novelty": 0.1}


@dataclass
class PriorityResult:
    priority: Priority
    score: float
    factors: dict[str, float]
    explanation: str


def prioritize(
    *,
    max_severity: int,
    threat_tier: int,
    category: str,
    confidence: float,
    confidence_level: str,
    novelty: float,
) -> PriorityResult:
    factors = {
        "impact": (max(1, min(5, max_severity)) - 1) / 4,
        "threat": (max(1, min(5, threat_tier)) - 1) / 4,
        "category": CATEGORY_WEIGHTS.get(category, 0.3),
        "confidence": max(0.0, min(1.0, confidence)),
        "novelty": max(0.0, min(1.0, novelty)),
    }
    score = sum(FACTOR_WEIGHTS[k] * v for k, v in factors.items())
    priority = Priority.low
    for threshold, p in PRIORITY_THRESHOLDS:
        if score >= threshold:
            priority = p
            break
    notes = []
    # Guardrails: never page people at critical on shaky evidence.
    if (
        confidence_level in (ConfidenceLevel.disputed, ConfidenceLevel.unverified)
        and priority.rank > Priority.medium.rank
    ):
        priority = Priority.medium
        notes.append(f"capped at medium because evidence is {confidence_level}")
    elif priority == Priority.critical and confidence_level != ConfidenceLevel.confirmed:
        priority = Priority.high
        notes.append(f"capped at high: critical requires confirmed evidence (is {confidence_level})")
    if (
        max_severity >= 5
        and confidence_level == ConfidenceLevel.confirmed
        and priority.rank < Priority.high.rank
    ):
        priority = Priority.high
        notes.append("raised to high: confirmed severity-5 impact")
    parts = ", ".join(f"{k}={v:.2f}×{FACTOR_WEIGHTS[k]}" for k, v in factors.items())
    explanation = f"score {score:.2f} ({parts}) -> {priority.value}" + (
        f"; {'; '.join(notes)}" if notes else ""
    )
    return PriorityResult(
        priority, round(score, 3), {k: round(v, 3) for k, v in factors.items()}, explanation
    )
