"""Builds the template context from a validated spec and its verified architecture plan."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.generator.render import docstring_text
from app.generator.samples import SampleBundle
from app.planner.architecture import END, START
from app.schemas.agent_spec import AgentSpec
from app.schemas.plan import ArchitecturePlan, ToolBinding

OLLAMA_VERSION = "0.12.6"
LONG_TEXT_FIELDS = {
    "body",
    "message",
    "content",
    "summary",
    "details",
    "description",
    "reason",
    "notes",
    "query",
    "text",
}
PYTHON_TYPES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}
ROUTERS = {
    "guard_input": "route_after_guard",
    "safety_check": "route_after_safety",
    "human_approval": "route_after_approval",
}
MODE_EXPLANATIONS = {
    "read": "read-only lookup; runs during the workflow without approval.",
    "draft": "prepares a side-effect-free preview while proposing actions and commits only in the "
    "execute step.",
    "execute": "changes an external system; runs only in the execute step after human approval.",
}
BASE_DEPENDENCIES = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.30,<1",
    "langgraph>=1.0,<2",
    "pydantic>=2.9,<3",
    "pydantic-settings>=2.5,<3",
    "httpx>=0.27,<1",
    "sqlalchemy>=2.0,<3",
    "structlog>=24.1",
    "PyYAML>=6,<7",
    "prometheus-client>=0.20,<1",
]


def display_name(name: str) -> str:
    return " ".join(word.upper() if len(word) <= 2 else word.capitalize() for word in name.split("_"))


def _class_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_")) + "Input"


def _tool_fields(binding: ToolBinding) -> list[dict[str, Any]]:
    fields = []
    for parameter in binding.inputs:
        annotation = PYTHON_TYPES[parameter.type]
        constraints: list[tuple[str, str]] = []
        if parameter.type == "string":
            if parameter.required:
                constraints.append(("min_length", "1"))
            constraints.append(("max_length", "8000" if parameter.name in LONG_TEXT_FIELDS else "500"))
        fields.append(
            {
                "name": parameter.name,
                "annotation": annotation if parameter.required else f"{annotation} | None",
                "default_expr": "..." if parameter.required else "None",
                "description": parameter.description,
                "constraints": constraints,
                "required": parameter.required,
                "type": parameter.type,
            }
        )
    return fields


def _tool_context(binding: ToolBinding) -> dict[str, Any]:
    fields = _tool_fields(binding)
    ordered = [field for field in fields if field["required"]] + [f for f in fields if not f["required"]]
    signature = ", ".join(
        f"{field['name']}: {field['annotation']}" + ("" if field["required"] else " = None")
        for field in ordered
    )
    arguments = "{" + ", ".join(f'"{field["name"]}": {field["name"]}' for field in fields) + "}"
    summary = ", ".join(
        f"{field['name']} ({field['type']}{', optional' if not field['required'] else ''})"
        for field in fields
    )
    return {
        "name": binding.name,
        "description": binding.description,
        "docstring": docstring_text(binding.description),
        "mode": binding.mode,
        "mode_explanation": MODE_EXPLANATIONS[binding.mode],
        "approval_required": binding.approval_required,
        "timeout_seconds": binding.timeout_seconds,
        "class_name": _class_name(binding.name),
        "fields": fields,
        "mcp_signature": signature,
        "mcp_arguments": arguments,
        "input_summary": summary,
    }


def _wiring(plan: ArchitecturePlan) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    order: list[str] = []
    plain: list[dict[str, Any]] = []
    for edge in plan.edges:
        if edge.source == START or edge.target == END:
            continue
        if edge.condition:
            if edge.source not in grouped:
                order.append(edge.source)
            grouped[edge.source][edge.condition] = edge.target
        else:
            plain.append(
                {"type": "edge", "source": edge.source, "target": edge.target, "_position": len(plain)}
            )
    wiring: list[dict[str, Any]] = []
    node_order = {node.id: node.order for node in plan.nodes}
    node_kind = {node.id: node.kind for node in plan.nodes}
    for source in order:
        router = ROUTERS.get(node_kind.get(source, ""))
        if router is None:
            raise ValueError(f"no router for conditional node {source}")
        wiring.append({"type": "conditional", "source": source, "router": router, "mapping": grouped[source]})
    wiring.extend(plain)
    wiring.sort(key=lambda item: node_order.get(item["source"], 0))
    return wiring


def build_context(
    spec: AgentSpec,
    plan: ArchitecturePlan,
    samples: SampleBundle,
    *,
    spec_hash: str,
    version: str,
) -> dict[str, Any]:
    nodes = {node.id: node for node in plan.nodes}
    steps = []
    for step in spec.workflow:
        node = nodes[step.id]
        bindings = ", ".join(f"`{name}`" for name in node.tools) or ", ".join(node.sources) or "—"
        steps.append(
            {
                "id": step.id,
                "kind": step.kind,
                "description": step.description or node.description,
                "docstring": docstring_text(step.description or node.description, indent=8, width=96),
                "tools": node.tools,
                "sources": node.sources if step.kind == "retrieve" else [],
                "labels": [
                    {"name": label.name, "description": label.description, "hints": list(label.hints)}
                    for label in step.labels
                ],
                "dimension": step.dimension,
                "review": step.review or "when_required",
                "bindings": bindings,
            }
        )
    tools = [_tool_context(binding) for binding in plan.tools]
    uses_postgres = spec.memory.type == "postgres" or (
        spec.retrieval.enabled and spec.retrieval.store == "pgvector"
    )
    checkpoint_backend = "postgres" if spec.memory.type == "postgres" else "sqlite"
    dependencies = list(BASE_DEPENDENCIES)
    if checkpoint_backend == "postgres" or uses_postgres:
        dependencies += ["langgraph-checkpoint-postgres>=2,<4", "psycopg[binary,pool]>=3.2,<4"]
    if checkpoint_backend == "sqlite":
        dependencies += ["langgraph-checkpoint-sqlite>=2,<4", "aiosqlite>=0.20"]
    counts = samples.dataset["counts"]
    dataset_summary = ", ".join(f"{count} {category.replace('_', ' ')}" for category, count in counts.items())
    topology_lines = []
    for edge in plan.edges:
        arrow = f" --{edge.condition}--> " if edge.condition else " --> "
        topology_lines.append(f"    {edge.source}{arrow}{edge.target}")
    package = spec.agent.name.replace("_", "-")
    return {
        "agentforge_version": version,
        "spec": spec,
        "spec_hash": spec_hash,
        "plan": plan,
        "agent": {
            "name": spec.agent.name,
            "display_name": display_name(spec.agent.name),
            "domain": spec.agent.domain,
            "objective": spec.agent.objective,
            "description": spec.agent.description,
            "constraints": list(spec.agent.constraints),
            "package": f"{package}-agent" if not package.endswith("agent") else package,
            "cli": package,
        },
        "model": spec.model.model_dump(),
        "workflow_ids": [step.id for step in spec.workflow],
        "steps": steps,
        "tools": tools,
        "read_tools": [tool for tool in tools if tool["mode"] == "read"],
        "wiring": _wiring(plan),
        "topology": {
            "nodes": [{"id": node.id, "kind": node.kind} for node in plan.nodes],
            "edges": [
                {"source": edge.source, "target": edge.target, "condition": edge.condition}
                for edge in plan.edges
            ],
        },
        "topology_diagram": "\n".join(topology_lines),
        "retrieval": {
            "enabled": spec.retrieval.enabled,
            "sources": list(spec.retrieval.source_names),
            "top_k": spec.retrieval.top_k,
            "min_score": spec.retrieval.min_score,
            "citations_required": spec.retrieval.citations_required,
            "chunk_size": spec.retrieval.chunk_size,
            "chunk_overlap": spec.retrieval.chunk_overlap,
            "embeddings": spec.retrieval.embeddings,
            "store": spec.retrieval.store if spec.retrieval.enabled else "memory",
        },
        "guardrails": {
            "injection_action": spec.guardrails.prompt_injection.action,
            "scan_retrieved_content": spec.guardrails.prompt_injection.scan_retrieved_content,
            "redact_logs": spec.guardrails.pii.redact_logs,
            "redact_memory": spec.guardrails.pii.redact_memory,
            "max_tool_calls": spec.guardrails.tool_execution.max_calls_per_run,
            "tool_timeout_seconds": spec.guardrails.tool_execution.timeout_seconds,
            "external_approval": spec.guardrails.external_messages.approval_required,
        },
        "memory": spec.memory.model_dump(),
        "memory_enabled": spec.memory.type != "none",
        "evaluation": spec.evaluation.model_dump(),
        "checkpoint_backend": checkpoint_backend,
        "uses_postgres": uses_postgres,
        "database_url_default": (
            "postgresql+psycopg://agent:change-me@localhost:5432/agent"
            if uses_postgres
            else "sqlite:///./var/agent.db"
        ),
        "postgres_image": "pgvector/pgvector:pg17"
        if spec.retrieval.store == "pgvector"
        else "postgres:17-alpine",
        "ollama_version": OLLAMA_VERSION,
        "dependencies": dependencies,
        "sample_request": samples.sample_request,
        "dataset_summary": dataset_summary,
        "tree": "",
    }
