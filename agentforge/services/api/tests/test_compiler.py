from app.services.compiler import compile_requirement, spec_hash

REQUIREMENT = """
Build a property maintenance triage agent. It should prepare work orders and email drafts,
require human approval, use local Qwen and Postgres memory, and target at least 92% task success.
"""


def test_compiler_is_deterministic() -> None:
    first, first_warnings = compile_requirement(REQUIREMENT)
    second, second_warnings = compile_requirement(REQUIREMENT)
    assert first == second
    assert first_warnings == second_warnings == []
    assert spec_hash(first) == spec_hash(second)


def test_compiler_enforces_requested_profile_and_safety() -> None:
    spec, _ = compile_requirement(REQUIREMENT)
    assert spec.agent.name == "maintenance_triage"
    assert spec.model.provider == "local"
    assert spec.memory.type == "postgres"
    assert spec.evaluation.task_success_target == 0.92
    assert spec.guardrails.external_messages.approval_required is True
    assert spec.workflow.index("human_approval") < spec.workflow.index("execute")
