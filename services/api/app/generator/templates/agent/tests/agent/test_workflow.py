"""End-to-end workflow behaviour on the functional, retrieval and assessment cases."""

from __future__ import annotations

from typing import Any

import pytest

from evals.run import grade_case, run_case
from src.agent import blueprint
from src.agent.service import AgentService
from src.tools.backends import FixtureBackend
from tests.support import case_ids, cases, run

WORKFLOW_CASES = cases("functional", "retrieval", "assessment")


@pytest.mark.parametrize("case", WORKFLOW_CASES, ids=case_ids)
def test_workflow_case(service: AgentService, backend: FixtureBackend, case: dict[str, Any]) -> None:
    result = grade_case(case, run(run_case(service, backend, case)))
    problems = result["task"]["details"] + (result["tools"] or {}).get("details", []) + result["safety"]["details"]
    assert result["passed"], problems


def test_audit_trail_records_every_node(service: AgentService) -> None:
    case = WORKFLOW_CASES[0]
    view = run(service.start(case["input"]))
    detailed = run(service.get(view.run_id, include_audit=True))
    nodes = {entry["node"] for entry in detailed.audit or []}
    assert "guard_input" in nodes
    assert len(nodes) >= 3


@pytest.mark.skipif(blueprint.MEMORY["type"] == "none", reason="conversation memory disabled")
def test_conversation_history_is_used(service: AgentService) -> None:
    case = WORKFLOW_CASES[0]
    run(service.start(case["input"], thread_id="history-thread"))
    history = run(service.runtime.memory.history("history-thread"))
    assert history and history[0]["role"] == "user"
