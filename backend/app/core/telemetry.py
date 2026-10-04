"""Prometheus metrics and OpenTelemetry tracing."""

from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram

from app.config import settings

FETCH_LATENCY = Histogram(
    "mr_fetch_seconds",
    "Source fetch latency",
    ["source_type", "method"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)
FETCH_ERRORS = Counter("mr_fetch_errors_total", "Source fetch failures", ["source_type", "reason"])
PIPELINE_OUTCOMES = Counter("mr_pipeline_outcomes_total", "Intel pipeline outcomes", ["outcome"])
NODE_LATENCY = Histogram(
    "mr_agent_node_seconds",
    "Agent node latency",
    ["node", "status"],
    buckets=(0.05, 0.25, 1, 5, 15, 60, 180, 600),
)
LLM_LATENCY = Histogram(
    "mr_llm_seconds", "LLM call latency", ["model", "task"], buckets=(0.5, 1, 5, 15, 30, 60, 120, 300)
)
LLM_TOKENS = Counter("mr_llm_tokens_total", "LLM tokens", ["model", "kind"])
LLM_FAILURES = Counter("mr_llm_failures_total", "LLM structured output failures", ["model", "task"])
EVENTS_CREATED = Counter("mr_events_total", "Intelligence events created", ["priority", "category"])
ALERTS_SENT = Counter("mr_alerts_total", "Alerts dispatched", ["channel", "status"])
BRIEFS_GENERATED = Counter("mr_briefs_total", "Daily briefs generated", ["role"])

_tracer_configured = False


def configure_tracing(service_name: str) -> None:
    global _tracer_configured
    if _tracer_configured:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    _tracer_configured = True


tracer = trace.get_tracer("marketradar")


@contextmanager
def span(name: str, **attrs: Any):
    with tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k, str(v))
        yield s
