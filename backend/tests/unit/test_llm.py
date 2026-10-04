import json
from types import SimpleNamespace

from app.llm.client import HeuristicProvider, OllamaProvider, llm_calls, render_prompt
from app.llm.heuristics import FALLBACKS, classify_change
from app.llm.schemas import ChangeClassification, ImpactAnalysis, PricingTable

MIN_CTX = {
    "competitor": "Acme",
    "source_name": "Pricing",
    "source_type": "pricing",
    "url": "http://x",
    "text": "t",
    "title": "t",
    "summary": "s",
    "category": "pricing",
    "claims": ["c"],
    "evidence_text": "e",
    "org_name": "o",
    "date": "2026-01-01",
    "events": [],
    "threat_tier": 3,
    "confidence_level": "likely",
    "description": "",
}


def test_all_prompts_render_with_minimal_context():
    for task in FALLBACKS:
        assert render_prompt(task, MIN_CTX)


def test_schema_validators_clamp():
    c = ChangeClassification(is_meaningful=True, category="PRICING", significance=7, title="t", summary="s")
    assert c.category == "pricing" and c.significance == 1.0
    odd = ChangeClassification(is_meaningful=True, category="weird", significance="x", title="t", summary="s")
    assert odd.category == "other" and odd.significance == 0.3


def test_heuristic_classifier_flags_price_moves():
    out = classify_change(
        {
            "competitor": "Acme",
            "added": ["Growth $99 / month"],
            "removed": ["Growth $79 / month"],
            "pricing_changes": [{"description": "Acme raised 'Growth' price from $79 to $99"}],
        }
    )
    assert out.category == "pricing" and out.significance >= 0.75 and out.is_meaningful


class _FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, **_):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(message=SimpleNamespace(content=r), prompt_eval_count=10, eval_count=5)


async def _complete(monkeypatch, replies, task, schema, ctx):
    fake = _FakeOllama(replies)
    monkeypatch.setattr(OllamaProvider, "client", property(lambda self: fake))
    calls: list = []
    token = llm_calls.set(calls)
    try:
        out = await OllamaProvider(host="http://ollama.test").complete(task, schema, ctx)
    finally:
        llm_calls.reset(token)
    return out, fake, calls


async def test_retries_invalid_json_then_succeeds(monkeypatch):
    good = json.dumps({"plans": [{"name": "Pro", "price": "$49"}]})
    out, fake, calls = await _complete(
        monkeypatch, ["{not json", good], "extract_pricing", PricingTable, {"competitor": "A", "text": "x"}
    )
    assert out.plans[0].price == 49.0
    assert fake.calls == 2 and calls[0]["attempts"] == 2


async def test_waits_out_gpu_oom_instead_of_falling_back(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_transient_backoff_seconds", 0.0)
    oom = Exception("llama-server reported out-of-memory during startup: cudaMalloc failed: out of memory")
    good = json.dumps({"plans": [{"name": "Pro", "price": 49}]})
    out, fake, calls = await _complete(
        monkeypatch, [oom, good], "extract_pricing", PricingTable, {"competitor": "A", "text": "x"}
    )
    assert out.plans[0].name == "Pro" and fake.calls == 2
    assert calls[0]["model"] != "heuristic"


async def test_falls_back_to_heuristic_when_unreachable(monkeypatch):
    out, _, calls = await _complete(
        monkeypatch, [ConnectionError("down")], "impact", ImpactAnalysis, {**MIN_CTX, "significance": 0.8}
    )
    assert isinstance(out, ImpactAnalysis) and 1 <= out.max_severity <= 5
    assert calls[0]["model"] == "heuristic"


async def test_heuristic_provider_has_no_embeddings():
    assert await HeuristicProvider().embed(["x"]) is None


def test_relationship_names_are_cleaned():
    from app.llm.heuristics import extract_entities
    from app.llm.schemas import clean_org_name

    assert clean_org_name("Snowflake to launch Globex Connect") == "Snowflake"
    assert clean_org_name("Andreessen Horowitz") == "Andreessen Horowitz"
    out = extract_entities(
        {
            "competitor": "Globex Data",
            "text": "Globex Data announced a strategic partnership with Snowflake and launched Globex Connect",
        }
    )
    assert [r.counterparty for r in out.relationships] == ["Snowflake"]
    assert [p.name for p in out.products] == ["Globex Connect"]
