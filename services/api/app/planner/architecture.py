"""Architecture planner: derives the agent graph from an AgentSpec and proves its safety properties.

The derived topology is a DAG::

    START -> guard_input -(continue)-> step_1 -> ... -> step_n -> finalize -> END
                         \\-(blocked)-> finalize
    safety_check   -(blocked)->  finalize
    human_approval -(rejected)-> finalize

Verified properties (each becomes a :class:`TopologyCheck`):

* every node is reachable from START and every node can reach END;
* the graph is acyclic;
* START's only successor is the input guard;
* human approval *dominates* every side-effecting node — removing the approval nodes makes all
  execute nodes unreachable, so no path can perform an external action without a decision;
* every side-effecting tool is only bound to proposal (draft) steps.
"""

from __future__ import annotations

from collections import defaultdict, deque

from app.planner.risk import assess_risk
from app.schemas.agent_spec import AgentSpec
from app.schemas.plan import (
    ArchitecturePlan,
    Component,
    PlanEdge,
    PlanNode,
    ToolBinding,
    ToolParameterPlan,
    TopologyCheck,
)

START = "__start__"
END = "__end__"

KIND_TITLES = {
    "guard_input": "Input guard",
    "classify": "Classify",
    "assess": "Assess",
    "retrieve": "Retrieve evidence",
    "lookup": "Tool lookup",
    "analyze": "Analyze",
    "draft": "Propose actions",
    "safety_check": "Safety check",
    "verify": "Verify grounding",
    "human_approval": "Human approval",
    "execute": "Execute approved actions",
    "respond": "Respond",
    "finalize": "Finalize & audit",
}

# Used when a hand-written specification leaves a step's description empty.
KIND_DESCRIPTIONS = {
    "classify": "Assign the request to one of the declared labels.",
    "assess": "Rate the request along the declared dimension.",
    "retrieve": "Retrieve relevant evidence from approved knowledge sources.",
    "lookup": "Look up context with read-only tools.",
    "analyze": "Reason over the evidence gathered so far.",
    "draft": "Propose actions and a reply for human review.",
    "safety_check": "Check proposed actions against the action policy.",
    "verify": "Check claims against the retrieved evidence.",
    "human_approval": "Pause for a reviewer to approve or reject the proposed actions.",
    "execute": "Run only the actions a reviewer approved, exactly as approved.",
    "respond": "Compose the final response.",
}

DEFAULT_QUERY_INPUT = ToolParameterPlan(
    name="query", type="string", description="Free-text request for the tool.", required=True
)


def resolve_tool_bindings(spec: AgentSpec) -> dict[str, list[str]]:
    """Map step id -> tool names after applying 'empty means all eligible tools' defaults."""
    bindings: dict[str, list[str]] = {}
    for step in spec.workflow:
        if step.kind == "lookup":
            bindings[step.id] = list(step.tools) or [t.name for t in spec.tools if t.mode == "read"]
        elif step.kind == "draft":
            bindings[step.id] = list(step.tools) or [t.name for t in spec.tools if t.mode != "read"]
    return bindings


def build_tool_plan(spec: AgentSpec, bindings: dict[str, list[str]]) -> list[ToolBinding]:
    execute_steps = [step.id for step in spec.workflow if step.kind == "execute"]
    plans: list[ToolBinding] = []
    for tool in spec.tools:
        used_by = [step_id for step_id, names in bindings.items() if tool.name in names]
        if tool.mode != "read":
            used_by.extend(execute_steps)
        inputs = [
            ToolParameterPlan(
                name=parameter.name,
                type=parameter.type,
                description=parameter.description or parameter.name.replace("_", " ").capitalize(),
                required=parameter.required,
            )
            for parameter in tool.inputs
        ] or [DEFAULT_QUERY_INPUT]
        plans.append(
            ToolBinding(
                name=tool.name,
                description=tool.description or tool.name.replace("_", " ").capitalize() + ".",
                mode=tool.mode,
                approval_required=spec.tool_requires_approval(tool),
                timeout_seconds=tool.timeout_seconds or spec.guardrails.tool_execution.timeout_seconds,
                inputs=inputs,
                used_by=used_by,
                phases={"read": ["read"], "draft": ["preview", "execute"], "execute": ["execute"]}[tool.mode],
            )
        )
    return plans


def build_graph(spec: AgentSpec, bindings: dict[str, list[str]]) -> tuple[list[PlanNode], list[PlanEdge]]:
    nodes = [
        PlanNode(
            id="guard_input",
            kind="guard_input",
            title=KIND_TITLES["guard_input"],
            description="Validate size, scan for prompt injection and redact PII before any model call.",
            platform=True,
            order=0,
        )
    ]
    for index, step in enumerate(spec.workflow, start=1):
        bound = bindings.get(step.id, [])
        sources = list(step.sources) or (list(spec.retrieval.source_names) if step.kind == "retrieve" else [])
        nodes.append(
            PlanNode(
                id=step.id,
                kind=step.kind,
                title=KIND_TITLES[step.kind],
                description=step.description or KIND_DESCRIPTIONS[step.kind],
                tools=bound,
                sources=sources,
                side_effects=step.kind == "execute",
                order=index,
            )
        )
    nodes.append(
        PlanNode(
            id="finalize",
            kind="finalize",
            title=KIND_TITLES["finalize"],
            description="Compose the outcome, persist memory and append the audit record.",
            platform=True,
            order=len(spec.workflow) + 1,
        )
    )

    step_ids = [step.id for step in spec.workflow]
    edges = [
        PlanEdge(source=START, target="guard_input"),
        PlanEdge(source="guard_input", target=step_ids[0], condition="continue"),
        PlanEdge(source="guard_input", target="finalize", condition="blocked"),
    ]
    for index, step in enumerate(spec.workflow):
        following = step_ids[index + 1] if index + 1 < len(step_ids) else "finalize"
        if step.kind == "safety_check":
            edges.append(PlanEdge(source=step.id, target=following, condition="continue"))
            edges.append(PlanEdge(source=step.id, target="finalize", condition="blocked"))
        elif step.kind == "human_approval":
            edges.append(PlanEdge(source=step.id, target=following, condition="approved"))
            if following != "finalize":
                edges.append(PlanEdge(source=step.id, target="finalize", condition="rejected"))
        else:
            edges.append(PlanEdge(source=step.id, target=following))
    edges.append(PlanEdge(source="finalize", target=END))
    return nodes, edges


def _adjacency(edges: list[PlanEdge], *, skip: set[str] | None = None) -> dict[str, list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if skip and (edge.source in skip or edge.target in skip):
            continue
        adjacency[edge.source].append(edge.target)
    return adjacency


def _reachable(adjacency: dict[str, list[str]], start: str) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        for target in adjacency.get(queue.popleft(), []):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _is_acyclic(node_ids: list[str], edges: list[PlanEdge]) -> bool:
    indegree = dict.fromkeys(node_ids, 0)
    adjacency = _adjacency(edges)
    for edge in edges:
        indegree[edge.target] = indegree.get(edge.target, 0) + 1
    queue = deque([node for node, degree in indegree.items() if degree == 0])
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for target in adjacency.get(node, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return visited == len(indegree)


def verify_topology(
    spec: AgentSpec, nodes: list[PlanNode], edges: list[PlanEdge], bindings: dict[str, list[str]]
) -> list[TopologyCheck]:
    node_ids = [START, *[node.id for node in nodes], END]
    forward = _adjacency(edges)
    reverse: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        reverse[edge.target].append(edge.source)

    unreachable = sorted(set(node_ids) - _reachable(forward, START))
    stuck = sorted(set(node_ids) - _reachable(reverse, END))
    approval_nodes = {node.id for node in nodes if node.kind == "human_approval"}
    execute_nodes = {node.id for node in nodes if node.kind == "execute"}
    bypass = sorted(execute_nodes & _reachable(_adjacency(edges, skip=approval_nodes), START))
    start_successors = forward.get(START, [])
    tools = {tool.name: tool for tool in spec.tools}
    misbound = sorted(
        f"{step_id}:{name}"
        for step_id, names in bindings.items()
        for name in names
        if tools[name].mode != "read"
        and not any(s.id == step_id and s.kind == "draft" for s in spec.workflow)
    )

    return [
        TopologyCheck(
            id="reachable",
            title="Every node is reachable from START",
            passed=not unreachable,
            detail="all nodes reachable" if not unreachable else f"unreachable: {unreachable}",
        ),
        TopologyCheck(
            id="terminates",
            title="Every node can reach END",
            passed=not stuck,
            detail="all nodes terminate" if not stuck else f"cannot terminate: {stuck}",
        ),
        TopologyCheck(
            id="acyclic",
            title="Graph is acyclic (bounded execution)",
            passed=_is_acyclic(node_ids, edges),
            detail="topological order exists",
        ),
        TopologyCheck(
            id="guarded_entry",
            title="Input guard is the only entry point",
            passed=start_successors == ["guard_input"],
            detail=f"START -> {start_successors}",
        ),
        TopologyCheck(
            id="approval_dominates_side_effects",
            title="Human approval dominates every side-effecting node",
            passed=not bypass,
            detail=(
                "no side-effecting nodes"
                if not execute_nodes
                else (
                    f"removing {sorted(approval_nodes)} disconnects {sorted(execute_nodes)}"
                    if not bypass
                    else f"reachable without approval: {bypass}"
                )
            ),
        ),
        TopologyCheck(
            id="side_effect_binding",
            title="Side-effecting tools are only proposed by draft steps",
            passed=not misbound,
            detail="bindings verified" if not misbound else f"misbound: {misbound}",
        ),
    ]


def render_mermaid(nodes: list[PlanNode], edges: list[PlanEdge]) -> str:
    """Mermaid flowchart. Only identifiers and fixed titles are emitted (never free text)."""
    shapes = {
        "guard_input": ("([", "])"),
        "finalize": ("([", "])"),
        "human_approval": ("{", "}"),
        "execute": ("[[", "]]"),
        "retrieve": ("[(", ")]"),
        "safety_check": ("{{", "}}"),
    }
    lines = ["flowchart TD", f"    {START}((start))", f"    {END}((end))"]
    for node in nodes:
        left, right = shapes.get(node.kind, ("[", "]"))
        lines.append(f'    {node.id}{left}"{node.id}<br/>{node.title}"{right}')
    for edge in edges:
        arrow = f" -- {edge.condition} --> " if edge.condition else " --> "
        lines.append(f"    {edge.source}{arrow}{edge.target}")
    return "\n".join(lines) + "\n"


def build_components(spec: AgentSpec) -> list[Component]:
    checkpoint = {"postgres": "PostgresSaver", "sqlite": "SqliteSaver", "none": "InMemorySaver"}[
        spec.memory.type
    ]
    components = [
        Component(
            id="api",
            title="HTTP API",
            technology="FastAPI",
            detail="Runs, approvals, health, metrics; API-key auth with separate approver keys.",
        ),
        Component(
            id="graph",
            title="Agent graph",
            technology=f"LangGraph + {checkpoint}",
            detail=f"{len(spec.workflow) + 2} nodes with durable approval interrupts.",
        ),
        Component(
            id="model",
            title="Model provider",
            technology=f"{spec.model.provider}/{spec.model.model}",
            detail="Structured JSON outputs validated with Pydantic; deterministic offline model for tests.",
        ),
        Component(
            id="tools",
            title="Tool gateway",
            technology="Typed allowlist registry",
            detail=f"{len(spec.tools)} tools with input schemas, timeouts and phase enforcement (fixture or HTTP backend).",
        ),
        Component(
            id="mcp",
            title="MCP server",
            technology="Model Context Protocol",
            detail="Exposes read-only tools and agent runs to MCP clients; approvals stay on the authenticated API.",
        ),
        Component(
            id="guardrails",
            title="Guardrails",
            technology="Injection + PII + action policy",
            detail=f"Prompt injection: {spec.guardrails.prompt_injection.action}; PII redaction in logs and memory.",
        ),
        Component(
            id="evals",
            title="Evaluation suite",
            technology="Dataset + graders",
            detail=f"Task, tool and safety graders with {spec.evaluation.adversarial_cases} adversarial cases.",
        ),
    ]
    if spec.retrieval.enabled:
        components.insert(
            3,
            Component(
                id="rag",
                title="Retrieval",
                technology=f"{spec.retrieval.embeddings} embeddings / {spec.retrieval.store}",
                detail=f"Sources: {', '.join(spec.retrieval.source_names)}; top_k={spec.retrieval.top_k}; retrieved text scanned for injection.",
            ),
        )
    if spec.memory.type != "none":
        components.insert(
            4,
            Component(
                id="memory",
                title="Conversation memory",
                technology=spec.memory.type,
                detail=f"Namespace '{spec.memory.namespace}', {spec.memory.pii_retention_days}-day retention, PII redacted.",
            ),
        )
    return components


def plan_architecture(spec: AgentSpec) -> ArchitecturePlan:
    bindings = resolve_tool_bindings(spec)
    nodes, edges = build_graph(spec, bindings)
    checks = verify_topology(spec, nodes, edges, bindings)
    tools = build_tool_plan(spec, bindings)
    risk = assess_risk(spec, checks, tools)
    return ArchitecturePlan(
        agent=spec.agent.name,
        nodes=nodes,
        edges=edges,
        tools=tools,
        checks=checks,
        risk=risk,
        components=build_components(spec),
        mermaid=render_mermaid(nodes, edges),
    )
