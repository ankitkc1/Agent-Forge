"""Human-in-the-loop guarantees: nothing executes before approval, approvals bind to content."""

from __future__ import annotations

import pytest

from src.agent.contracts import ApprovalDecision
from src.agent.service import AgentService, RunNotAwaitingApprovalError
from src.tools.backends import FixtureBackend
from tests.support import cases, run

GATED = [case for case in cases("functional") if case["expect"].get("first_status") == "awaiting_approval"]
pytestmark = pytest.mark.skipif(not GATED, reason="agent has no approval-gated actions")


def start_gated(service: AgentService):  # type: ignore[no-untyped-def]
    view = run(service.start(GATED[0]["input"]))
    assert view.status == "awaiting_approval"
    assert view.pending_approval and view.pending_approval.actions
    return view


def test_nothing_executes_before_approval(service: AgentService, backend: FixtureBackend) -> None:
    start_gated(service)
    assert backend.journal == []


def test_approval_executes_exactly_the_proposed_actions(service: AgentService, backend: FixtureBackend) -> None:
    view = start_gated(service)
    result = run(service.resume(view.run_id, ApprovalDecision(approved=True, reviewer="tester")))
    assert result.status == "completed"
    executed = sorted(entry["tool"] for entry in backend.journal)
    assert executed == sorted(GATED[0]["expect"]["executed_tools"])
    proposed = {action["tool"]: action["arguments"] for action in view.proposed_actions}
    for entry in backend.journal:
        assert entry["arguments"] == proposed[entry["tool"]]


def test_partial_approval(service: AgentService, backend: FixtureBackend) -> None:
    view = start_gated(service)
    actions = view.pending_approval.actions  # type: ignore[union-attr]
    chosen = actions[0]["id"]
    result = run(service.resume(view.run_id, ApprovalDecision(approved=True, reviewer="tester", action_ids=[chosen])))
    executed_ids = {a["action_id"] for a in result.executed_actions if a["status"] == "executed"}
    approval_gated = {action["id"] for action in actions}
    assert chosen in executed_ids
    assert not (executed_ids & approval_gated) - {chosen}


def test_rejection_executes_nothing(service: AgentService, backend: FixtureBackend) -> None:
    view = start_gated(service)
    result = run(service.resume(view.run_id, ApprovalDecision(approved=False, reviewer="tester", comment="no")))
    assert result.status == "rejected"
    assert backend.journal == []
    assert "not approved" in (result.response or "")


def test_tampered_action_is_not_executed(service: AgentService, backend: FixtureBackend) -> None:
    view = start_gated(service)
    config = service._config(view.run_id)
    snapshot = run(service.graph.aget_state(config))
    original = snapshot.values["proposed_actions"][0]
    tampered = {**original, "arguments": {**original["arguments"], "__injected__": "exfiltrate"}}
    run(service.graph.aupdate_state(config, {"proposed_actions": [tampered]}))
    run(service.resume(view.run_id, ApprovalDecision(approved=True, reviewer="tester")))
    assert all("__injected__" not in entry["arguments"] for entry in backend.journal)
    final = run(service.graph.aget_state(config)).values
    assert any(event["type"] == "approval_mismatch" for event in final.get("security_events", []))


def test_resume_requires_a_pending_approval(service: AgentService) -> None:
    view = start_gated(service)
    run(service.resume(view.run_id, ApprovalDecision(approved=False, reviewer="tester")))
    with pytest.raises(RunNotAwaitingApprovalError):
        run(service.resume(view.run_id, ApprovalDecision(approved=True, reviewer="tester")))
