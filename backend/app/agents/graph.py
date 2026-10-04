"""LangGraph orchestration of the intelligence pipeline.

START -> scout --(changed)--> change_detection --(per significant change: Send)--> investigate -> END
              \\--(unchanged/error)--> END            \\--(nothing significant)--> END

investigate (subgraph):  research -> verification -> knowledge -> impact -> prioritize -> alert
                              \\--(duplicate of an existing event)--> END
"""

from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from app.agents.nodes.alert import alert_node
from app.agents.nodes.change_detection import change_detection_node
from app.agents.nodes.impact import impact_node
from app.agents.nodes.knowledge import knowledge_node
from app.agents.nodes.prioritize import prioritize_node
from app.agents.nodes.research import research_node
from app.agents.nodes.scout import scout_node
from app.agents.nodes.verification import verification_node
from app.agents.state import IntelState, InvestigationOutput, InvestigationState
from app.config import settings

NETWORK_RETRY = RetryPolicy(max_attempts=3, initial_interval=2.0, backoff_factor=2.0)


def build_investigation_graph():
    g = StateGraph(InvestigationState, output_schema=InvestigationOutput)
    g.add_node("research", research_node, retry_policy=NETWORK_RETRY)
    g.add_node("verification", verification_node, retry_policy=NETWORK_RETRY)
    g.add_node("knowledge", knowledge_node)
    g.add_node("impact", impact_node, retry_policy=NETWORK_RETRY)
    g.add_node("prioritize", prioritize_node)
    g.add_node("alert", alert_node)
    g.add_edge(START, "research")
    g.add_conditional_edges(
        "research", lambda s: END if s.get("duplicate_of") else "verification", ["verification", END]
    )
    g.add_edge("verification", "knowledge")
    g.add_edge("knowledge", "impact")
    g.add_edge("impact", "prioritize")
    g.add_edge("prioritize", "alert")
    g.add_edge("alert", END)
    return g.compile()


def route_after_scout(state: dict[str, Any]) -> str:
    return "change_detection" if state.get("scout_status") in ("changed", "first_snapshot") else END


def fan_out_investigations(state: dict[str, Any]) -> list[Send] | str:
    sends = [
        Send(
            "investigate",
            {
                "org_id": state["org_id"],
                "run_id": state["run_id"],
                "source_id": state["source_id"],
                "change_id": c["change_id"],
            },
        )
        for c in state.get("changes", [])
        if c.get("is_significant")
    ]
    return sends or END


def build_intel_graph():
    g = StateGraph(IntelState)
    g.add_node("scout", scout_node, retry_policy=RetryPolicy(max_attempts=2, initial_interval=5.0))
    g.add_node("change_detection", change_detection_node, retry_policy=NETWORK_RETRY)
    g.add_node("investigate", build_investigation_graph())
    g.add_edge(START, "scout")
    g.add_conditional_edges("scout", route_after_scout, ["change_detection", END])
    g.add_conditional_edges("change_detection", fan_out_investigations, ["investigate", END])
    g.add_edge("investigate", END)
    return g


_memory_saver = InMemorySaver()


@asynccontextmanager
async def checkpointer(owner: bool = False):
    """Postgres checkpointer (durable, resumable runs) with in-memory fallback for tests.
    `owner=True` connects with the migration role (needed to create the checkpoint tables)."""
    if settings.use_postgres_checkpointer:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        url = (settings.migration_database_url if owner else None) or settings.database_url
        async with AsyncPostgresSaver.from_conn_string(url.replace("+asyncpg", "")) as saver:
            yield saver
    else:
        yield _memory_saver


async def setup_checkpointer() -> None:
    if settings.use_postgres_checkpointer:
        async with checkpointer(owner=True) as saver:
            await saver.setup()
