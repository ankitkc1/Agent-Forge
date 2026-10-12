"""Assemble a validated AgentSpec from a RequirementAnalysis.

Workflow steps are laid out in a canonical, auditable order:

    classify -> assess -> plan* -> retrieve -> lookup -> analyze* -> draft -> safety_check
             -> verify -> human_approval -> execute -> respond

Steps are only included when the analysis calls for them, and the safety invariants enforced by
:class:`AgentSpec` (approval before execution, approval after approval-gated drafts) hold by
construction.
"""

from __future__ import annotations

from typing import Any

from app.compiler.analyzer import RequirementAnalysis
from app.compiler.domains import LabelTemplate
from app.schemas.agent_spec import AgentSpec


def _labels(labels: tuple[LabelTemplate, ...]) -> list[dict[str, Any]]:
    return [
        {"name": label.name, "description": label.description, "hints": list(label.hints)} for label in labels
    ]


def build_spec_document(analysis: RequirementAnalysis) -> dict[str, Any]:
    pack = analysis.pack
    read_tools = [tool for tool in analysis.tools if tool.mode == "read"]
    action_tools = [tool for tool in analysis.tools if tool.mode != "read"]
    noun = pack.entity.noun

    steps: list[dict[str, Any]] = [
        {
            "id": pack.classify_step,
            "kind": "classify",
            "description": f"Classify the incoming {noun} request into one category.",
            "labels": _labels(analysis.labels),
        }
    ]
    if analysis.wants_assess and analysis.dimension:
        steps.append(
            {
                "id": pack.assess_step or f"assess_{analysis.dimension}",
                "kind": "assess",
                "description": f"Assess the {analysis.dimension} of the request.",
                "dimension": analysis.dimension,
                "labels": _labels(analysis.levels),
            }
        )
    planning = [step for step in pack.analyze_steps if step[0].startswith("plan")]
    analysis_steps = [step for step in pack.analyze_steps if not step[0].startswith("plan")]
    for step_id, description in planning:
        steps.append({"id": step_id, "kind": "analyze", "description": description})
    if analysis.retrieval_enabled:
        steps.append(
            {
                "id": pack.retrieve_step,
                "kind": "retrieve",
                "description": "Retrieve relevant evidence from approved knowledge sources.",
            }
        )
    if read_tools:
        steps.append(
            {
                "id": pack.lookup_step,
                "kind": "lookup",
                "description": f"Look up {noun} context with read-only tools.",
                "tools": [tool.name for tool in read_tools],
            }
        )
    for step_id, description in analysis_steps:
        steps.append({"id": step_id, "kind": "analyze", "description": description})
    if action_tools:
        steps.append(
            {
                "id": pack.draft_step,
                "kind": "draft",
                "description": "Prepare proposed actions and drafts for human review.",
                "tools": [tool.name for tool in action_tools],
            }
        )
        steps.append(
            {
                "id": "safety_check",
                "kind": "safety_check",
                "description": "Check proposed actions against policy, PII exposure and injection signals.",
            }
        )
    if analysis.citations:
        steps.append(
            {
                "id": "verify_citations",
                "kind": "verify",
                "description": "Verify that the answer cites retrieved evidence for its claims.",
            }
        )
    needs_review_gate = bool(action_tools) or analysis.approval_explicit or analysis.citations
    if needs_review_gate:
        steps.append(
            {
                "id": pack.approval_step,
                "kind": "human_approval",
                "description": "Pause for a human decision on proposed actions or flagged output.",
                "review": "always" if analysis.review_always else "when_required",
            }
        )
    if action_tools and needs_review_gate:
        steps.append(
            {
                "id": "execute",
                "kind": "execute",
                "description": "Execute only the actions a reviewer approved, exactly as approved.",
            }
        )
    steps.append(
        {
            "id": pack.respond_step,
            "kind": "respond",
            "description": "Compose the final response with evidence, actions taken and next steps.",
        }
    )

    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "mode": tool.mode,
            "approval_required": tool.mode != "read",
            "inputs": [
                {"name": name, "type": kind, "description": description, "required": required}
                for name, kind, description, required in tool.inputs
            ],
        }
        for tool in analysis.tools
    ]
    memory_type = analysis.memory
    if analysis.store == "pgvector":
        memory_type = "postgres"
    return {
        "version": "1.0",
        "agent": {
            "name": analysis.agent_name,
            "domain": pack.key,
            "objective": analysis.objective,
            "description": analysis.description,
            "constraints": analysis.constraints,
        },
        "model": {
            "provider": analysis.provider,
            "model": analysis.model,
            "temperature": 0.1,
            "max_output_tokens": 1024,
        },
        "tools": tools,
        "retrieval": {
            "enabled": analysis.retrieval_enabled,
            "sources": [
                {"name": source.name, "description": source.description} for source in analysis.sources
            ],
            "top_k": 4,
            "min_score": 0.05,
            "citations_required": analysis.citations,
            "chunk_size": 800,
            "chunk_overlap": 120,
            "embeddings": analysis.embeddings,
            "store": analysis.store,
        },
        "workflow": steps,
        "guardrails": {
            "external_messages": {"approval_required": True},
            "tool_execution": {"allowlist_only": True, "timeout_seconds": 30, "max_calls_per_run": 12},
            "prompt_injection": {"action": "block_and_log", "scan_retrieved_content": True},
            "pii": {"redact_logs": True, "redact_memory": True},
        },
        "memory": {
            "type": memory_type,
            "namespace": analysis.agent_name,
            "pii_retention_days": 30,
            "conversation_window": 10,
        },
        "evaluation": {
            "task_success_target": analysis.task_success_target,
            "tool_accuracy_target": analysis.tool_accuracy_target,
            "unsafe_action_target": analysis.unsafe_action_target,
            "adversarial_cases": 18,
        },
    }


def assemble_spec(analysis: RequirementAnalysis) -> AgentSpec:
    return AgentSpec.model_validate(build_spec_document(analysis))
