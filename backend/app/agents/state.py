import operator
from typing import Annotated, Any, TypedDict


class IntelState(TypedDict, total=False):
    """State of one monitoring pass over one source (the parent graph)."""

    org_id: str
    source_id: str
    run_id: str
    trigger: str
    # Scout Agent
    scout_status: str  # changed | first_snapshot | unchanged | not_modified | error
    snapshot_id: str | None
    prev_snapshot_id: str | None
    # Change Detection Agent
    changes: list[dict[str, Any]]
    # Fan-in from parallel investigations
    events: Annotated[list[dict[str, Any]], operator.add]
    duplicates: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]


class InvestigationState(TypedDict, total=False):
    """State of one investigation (Research -> Verification -> Knowledge -> Impact -> Prioritize -> Alert)."""

    org_id: str
    run_id: str
    source_id: str
    change_id: str
    event_id: str | None
    duplicate_of: str | None
    claims: list[str]
    kb_context: list[dict[str, Any]]
    confidence: dict[str, Any]
    impact: dict[str, Any]
    priority: dict[str, Any]
    events: Annotated[list[dict[str, Any]], operator.add]
    duplicates: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]


class InvestigationOutput(TypedDict, total=False):
    events: Annotated[list[dict[str, Any]], operator.add]
    duplicates: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
