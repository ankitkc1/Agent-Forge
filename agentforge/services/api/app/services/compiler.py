from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from app.schemas.agent_spec import (
    AgentIdentity,
    AgentSpec,
    EvaluationConfig,
    ExternalMessageGuardrail,
    Guardrails,
    MemoryConfig,
    ModelConfig,
    PromptInjectionGuardrail,
    RetrievalConfig,
    ToolExecutionGuardrail,
    ToolSpec,
)


@dataclass(frozen=True)
class Profile:
    name: str
    objective: str
    description: str
    tools: tuple[tuple[str, str], ...]
    sources: tuple[str, ...]
    workflow: tuple[str, ...]


PROFILES: dict[str, Profile] = {
    "maintenance": Profile(
        name="maintenance_triage",
        objective="Triage property maintenance requests",
        description=(
            "Classify tenant requests, assess urgency, gather property context, and prepare "
            "governed maintenance actions."
        ),
        tools=(
            ("property_lookup", "read"),
            ("create_work_order", "draft"),
            ("email_draft", "draft"),
        ),
        sources=("property_documents", "maintenance_policies"),
        workflow=(
            "classify_request",
            "assess_urgency",
            "retrieve_property",
            "prepare_action",
            "human_approval",
            "execute",
        ),
    ),
    "support": Profile(
        name="customer_support",
        objective="Resolve customer support requests safely",
        description=(
            "Triage support tickets, retrieve verified product context, and prepare responses "
            "with explicit escalation boundaries."
        ),
        tools=(
            ("account_lookup", "read"),
            ("knowledge_search", "read"),
            ("reply_draft", "draft"),
            ("ticket_escalation", "draft"),
        ),
        sources=("product_documentation", "support_policies"),
        workflow=(
            "classify_ticket",
            "retrieve_context",
            "prepare_response",
            "safety_check",
            "human_approval",
            "execute",
        ),
    ),
    "research": Profile(
        name="market_research",
        objective="Produce evidence-backed market research briefings",
        description=(
            "Plan research, collect approved evidence, compare findings, and produce a fully "
            "cited briefing for review."
        ),
        tools=(("web_search", "read"), ("source_reader", "read"), ("citation_checker", "read")),
        sources=("approved_web_sources", "research_library"),
        workflow=(
            "plan_research",
            "gather_sources",
            "extract_evidence",
            "compare_findings",
            "verify_citations",
            "human_review",
            "publish_brief",
        ),
    ),
    "operations": Profile(
        name="incident_coordinator",
        objective="Coordinate operational incidents and response plans",
        description=(
            "Assess incidents, retrieve controlled runbooks, identify owners, and prepare "
            "governed operational communications."
        ),
        tools=(("runbook_search", "read"), ("owner_lookup", "read"), ("status_draft", "draft")),
        sources=("runbooks", "incident_history"),
        workflow=(
            "classify_incident",
            "assess_severity",
            "retrieve_runbook",
            "prepare_response",
            "human_approval",
            "execute",
        ),
    ),
}


def _profile_for(requirement: str) -> tuple[Profile, list[str]]:
    lower = requirement.casefold()
    if re.search(r"maintenance|property|tenant|work order", lower):
        return PROFILES["maintenance"], []
    if re.search(r"customer support|support ticket|customer|saas", lower):
        return PROFILES["support"], []
    if re.search(r"research|market|competitor|briefing", lower):
        return PROFILES["research"], []
    if re.search(r"incident|operations|runbook", lower):
        return PROFILES["operations"], []
    return PROFILES["support"], [
        "No domain profile matched with high confidence; the governed support profile was selected."
    ]


def compile_requirement(requirement: str) -> tuple[AgentSpec, list[str]]:
    normalized = " ".join(requirement.split())
    lower = normalized.casefold()
    profile, warnings = _profile_for(normalized)
    provider = (
        "local"
        if "local" in lower or "qwen" in lower
        else "anthropic"
        if "anthropic" in lower
        else "openai"
    )
    model = (
        "qwen2.5:14b"
        if "qwen" in lower
        else "claude-sonnet"
        if provider == "anthropic"
        else "gpt-5-mini"
    )
    memory = "postgres" if "postgres" in lower else "sqlite"
    match = re.search(r"(?:target|at least)\s+(\d{2,3})\s*%", lower)
    target = min(1.0, int(match.group(1)) / 100) if match else 0.9

    spec = AgentSpec(
        agent=AgentIdentity(
            name=profile.name, objective=profile.objective, description=profile.description
        ),
        model=ModelConfig(provider=provider, model=model, temperature=0.1),
        tools=tuple(
            ToolSpec(name=name, mode=mode, approval_required=mode in {"draft", "execute"})
            for name, mode in profile.tools
        ),
        retrieval=RetrievalConfig(
            enabled=True,
            sources=profile.sources,
            citations_required=profile.name == "market_research",
        ),
        workflow=profile.workflow,
        guardrails=Guardrails(
            external_messages=ExternalMessageGuardrail(approval_required=True),
            tool_execution=ToolExecutionGuardrail(allowlist_only=True, timeout_seconds=30),
            prompt_injection=PromptInjectionGuardrail(action="block_and_log"),
        ),
        memory=MemoryConfig(type=memory, namespace=profile.name, pii_retention_days=30),
        evaluation=EvaluationConfig(
            task_success_target=target,
            tool_accuracy_target=0.95,
            unsafe_action_target=0,
            adversarial_cases=18,
        ),
    )
    return spec, warnings


def canonical_spec(spec: AgentSpec) -> bytes:
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def spec_hash(spec: AgentSpec) -> str:
    return hashlib.sha256(canonical_spec(spec)).hexdigest()
