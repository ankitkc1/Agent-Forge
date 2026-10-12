from app.compiler import compile_requirement
from app.compiler.templates import TEMPLATES
from app.planner.architecture import (
    END,
    START,
    build_graph,
    plan_architecture,
    resolve_tool_bindings,
    verify_topology,
)
from app.schemas.plan import PlanEdge


def _spec(template_id: str = "maintenance-triage"):
    template = next(t for t in TEMPLATES if t.id == template_id)
    return compile_requirement(template.requirement).spec


def test_all_templates_produce_verified_plans() -> None:
    for template in TEMPLATES:
        plan = plan_architecture(compile_requirement(template.requirement).spec)
        assert plan.passed, (template.id, [c for c in plan.checks if not c.passed])
        assert plan.nodes[0].id == "guard_input"
        assert plan.nodes[-1].id == "finalize"


def test_graph_shape_matches_workflow_order() -> None:
    spec = _spec()
    plan = plan_architecture(spec)
    assert [node.id for node in plan.nodes[1:-1]] == [step.id for step in spec.workflow]
    conditional = {(edge.source, edge.condition) for edge in plan.edges if edge.condition}
    assert ("guard_input", "blocked") in conditional
    assert ("safety_check", "blocked") in conditional
    assert ("human_approval", "rejected") in conditional
    assert plan.edges[0].source == START and plan.edges[-1].target == END


def test_approval_bypass_is_detected() -> None:
    spec = _spec()
    bindings = resolve_tool_bindings(spec)
    nodes, edges = build_graph(spec, bindings)
    tampered = [*edges, PlanEdge(source="safety_check", target="execute", condition="shortcut")]
    checks = {check.id: check for check in verify_topology(spec, nodes, tampered, bindings)}
    assert not checks["approval_dominates_side_effects"].passed
    assert "execute" in checks["approval_dominates_side_effects"].detail


def test_cycle_is_detected() -> None:
    spec = _spec()
    bindings = resolve_tool_bindings(spec)
    nodes, edges = build_graph(spec, bindings)
    tampered = [*edges, PlanEdge(source="respond", target="classify_request")]
    checks = {check.id: check for check in verify_topology(spec, nodes, tampered, bindings)}
    assert not checks["acyclic"].passed


def test_tool_bindings_and_phases() -> None:
    plan = plan_architecture(_spec())
    tools = {tool.name: tool for tool in plan.tools}
    assert tools["property_lookup"].phases == ["read"]
    assert tools["create_work_order"].phases == ["preview", "execute"]
    assert tools["send_tenant_email"].approval_required is True
    assert "execute" in tools["send_tenant_email"].used_by


def test_risk_register_flags_blocking_topology_failures() -> None:
    plan = plan_architecture(_spec())
    side_effects = next(f for f in plan.risk.findings if f.id == "ACTIONS-EXTERNAL-SIDE-EFFECTS")
    assert side_effects.status == "mitigated"
    assert not plan.risk.blocking


def test_mermaid_contains_only_identifiers() -> None:
    spec = _spec()
    plan = plan_architecture(spec)
    assert plan.mermaid.startswith("flowchart TD")
    assert spec.agent.description not in plan.mermaid
