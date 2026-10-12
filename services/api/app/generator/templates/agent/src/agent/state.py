"""Graph state shared by every node.

Lists that several nodes contribute to use additive reducers, so nodes return only what they
add. Everything stored here is plain JSON so any LangGraph checkpointer can persist it.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from src.agent.contracts import RunStatus


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class AgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    request_id: str
    user_input: str
    history: list[dict[str, str]]
    status: RunStatus

    classification: dict[str, Any]
    assessments: Annotated[dict[str, dict[str, Any]], merge_dicts]
    evidence: Annotated[list[dict[str, Any]], operator.add]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    notes: Annotated[dict[str, dict[str, Any]], merge_dicts]
    proposed_actions: Annotated[list[dict[str, Any]], operator.add]
    approval: dict[str, Any]
    executed_actions: Annotated[list[dict[str, Any]], operator.add]
    tool_calls: Annotated[int, operator.add]

    blocked: bool
    block_reasons: Annotated[list[str], operator.add]
    needs_review: bool
    review_reasons: Annotated[list[str], operator.add]
    security_events: Annotated[list[dict[str, Any]], operator.add]

    draft_response: str
    final_response: str
    audit_log: Annotated[list[dict[str, Any]], operator.add]
