"""Node archetypes. Each workflow step in ``nodes.py`` delegates to one of these functions.

Every function receives the runtime, the current state and the step configuration, and returns
a *partial* state update. Nothing here raises for ordinary failures (tool errors, invalid model
output): failures are recorded in the state and surfaced in the response and audit log.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt
from pydantic import ValidationError

from src.agent import blueprint, textmatch
from src.agent.contracts import (
    AnalysisOutput,
    ApprovalDecision,
    AssessmentOutput,
    ClassificationOutput,
    DraftOutput,
    ResponseOutput,
    StepConfig,
    ToolArgumentsOutput,
    VerificationOutput,
    action_digest,
)
from src.agent.llm import ModelError
from src.agent.offline import ID_PATTERN
from src.agent.runtime import AgentRuntime
from src.agent.state import AgentState
from src.guardrails.injection import scan
from src.guardrails.pii import redact_value
from src.guardrails.policy import PolicyFinding
from src.observability import APPROVALS, GUARDRAIL_EVENTS, NODE_LATENCY, RUNS
from src.tools.base import ToolContext, ToolMode

EVIDENCE_CHARS = 700
HISTORY_TURNS = 4


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def timed(node: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        NODE_LATENCY.labels(node).observe(time.perf_counter() - started)


def audit(node: str, event: str, **data: Any) -> dict[str, Any]:
    payload = redact_value(data) if blueprint.GUARDRAILS["redact_logs"] else data
    return {"ts": now_iso(), "node": node, "event": event, "data": payload}


def tool_context(state: AgentState, phase: str) -> ToolContext:
    return ToolContext(
        run_id=state.get("run_id", "run"),
        thread_id=state.get("thread_id", "thread"),
        request_id=state.get("request_id", "request"),
        phase=phase,  # type: ignore[arg-type]
    )


def gather_facts(state: AgentState) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    classification = state.get("classification") or {}
    if classification.get("label"):
        facts["category"] = classification["label"]
    for assessment in (state.get("assessments") or {}).values():
        dimension, level = assessment.get("dimension"), assessment.get("level")
        if dimension and level:
            facts[dimension] = level
            facts.setdefault("dimension", dimension)
            facts.setdefault("level", level)
    identifiers = ID_PATTERN.findall(state.get("user_input", ""))
    if identifiers:
        facts["entity_id"] = identifiers[0]
    for result in state.get("tool_results", []):
        data = result.get("data") or {}
        if result.get("ok") and isinstance(data.get("record"), dict):
            for key, value in data["record"].items():
                if isinstance(value, str | int | float | bool):
                    facts.setdefault(key, value)
    return facts


def visible_evidence(state: AgentState) -> list[dict[str, Any]]:
    return [
        {
            "citation": item["citation"],
            "source": item["source"],
            "title": item["title"],
            "text": item["text"][:EVIDENCE_CHARS],
        }
        for item in state.get("evidence", [])
    ]


def visible_tool_results(state: AgentState) -> list[dict[str, Any]]:
    return [
        {"tool": result["tool"], "ok": result["ok"], "data": result.get("data"), "error": result.get("error")}
        for result in state.get("tool_results", [])
        if not result.get("quarantined")
    ]


def recent_history(state: AgentState) -> list[dict[str, str]]:
    return list(state.get("history", []))[-HISTORY_TURNS:]


def _labels(step: StepConfig) -> list[dict[str, Any]]:
    return [
        {"name": label.name, "description": label.description, "hints": list(label.hints)}
        for label in step.labels
    ]


def _model_failure(node: str, exc: Exception) -> dict[str, Any]:
    return {
        "needs_review": True,
        "review_reasons": [f"The model could not complete '{node}' reliably; human review required."],
        "audit_log": [audit(node, "model_error", error=str(exc)[:300])],
    }


def _quarantine_if_injected(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not blueprint.GUARDRAILS["scan_retrieved_content"]:
        return data, []
    text = " ".join(str(value) for value in _flatten(data))
    verdict = scan(text, profile="retrieved")
    if verdict.suspicious:
        return {"quarantined": True}, list(verdict.rules)
    return data, []


def _flatten(value: Any) -> Iterator[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _flatten(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _flatten(item)
    else:
        yield value


# --------------------------------------------------------------------------------------------
# platform nodes
# --------------------------------------------------------------------------------------------


async def guard_input(rt: AgentRuntime, state: AgentState) -> dict[str, Any]:
    with timed("guard_input"):
        text = state.get("user_input", "")
        if not text.strip():
            return {"blocked": True, "block_reasons": ["The request was empty."], "audit_log": [audit("guard_input", "blocked", reason="empty")]}
        if len(text) > rt.settings.request_max_chars:
            return {
                "blocked": True,
                "block_reasons": [f"The request exceeds {rt.settings.request_max_chars} characters."],
                "audit_log": [audit("guard_input", "blocked", reason="too_long")],
            }
        verdict = scan(text, profile="input")
        if verdict.suspicious:
            GUARDRAIL_EVENTS.labels("prompt_injection").inc()
            event = {
                "type": "prompt_injection",
                "node": "guard_input",
                "score": verdict.score,
                "rules": list(verdict.rules),
                "ts": now_iso(),
            }
            if blueprint.GUARDRAILS["injection_action"] == "human_review":
                return {
                    "needs_review": True,
                    "review_reasons": ["The request contains instruction-like content and needs review."],
                    "security_events": [event],
                    "audit_log": [audit("guard_input", "flagged_for_review", rules=list(verdict.rules))],
                }
            return {
                "blocked": True,
                "block_reasons": ["The request was blocked by the prompt-injection guard."],
                "security_events": [event],
                "audit_log": [audit("guard_input", "blocked", rules=list(verdict.rules), score=verdict.score)],
            }
        return {"blocked": False, "audit_log": [audit("guard_input", "passed")]}


def route_after_guard(state: AgentState) -> str:
    return "blocked" if state.get("blocked") else "continue"


def route_after_safety(state: AgentState) -> str:
    return "blocked" if state.get("blocked") else "continue"


def route_after_approval(state: AgentState) -> str:
    status = (state.get("approval") or {}).get("status")
    return "approved" if status in {"approved", "not_required"} else "rejected"


async def finalize(rt: AgentRuntime, state: AgentState) -> dict[str, Any]:
    with timed("finalize"):
        approval = state.get("approval") or {}
        if state.get("blocked"):
            status = "blocked"
            reasons = " ".join(state.get("block_reasons", [])) or "The request was blocked."
            response = f"I can't act on this request. {reasons} The attempt has been logged."
        elif approval.get("status") == "rejected":
            status = "rejected"
            reviewer = approval.get("reviewer", "the reviewer")
            comment = f" Reviewer comment: {approval['comment']}" if approval.get("comment") else ""
            if any(action.get("requires_approval") for action in state.get("proposed_actions", [])):
                response = f"The proposed actions were not approved by {reviewer}; nothing was executed.{comment}"
            else:
                response = f"The response was not approved by {reviewer} and was withheld.{comment}"
        else:
            status = "completed"
            response = state.get("final_response") or state.get("draft_response") or "Request processed."
        RUNS.labels(status).inc()
        return {"status": status, "final_response": response, "audit_log": [audit("finalize", status)]}


# --------------------------------------------------------------------------------------------
# workflow archetypes
# --------------------------------------------------------------------------------------------


async def classify(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        labels = _labels(step)
        names = [label["name"] for label in labels]
        context = {"text": state["user_input"], "labels": labels, "history": recent_history(state)}
        try:
            output = await rt.structured("classify", step, context, ClassificationOutput)
        except ModelError as exc:
            fallback = textmatch.fallback_label(names)
            return {"classification": {"step": step.id, "label": fallback, "confidence": 0.0, "rationale": "model error"}, **_model_failure(step.id, exc)}
        label, confidence = output.label, output.confidence
        update: dict[str, Any] = {}
        if label not in names:
            update["review_reasons"] = [f"Model returned unknown label '{label[:40]}'."]
            label, confidence = textmatch.fallback_label(names), 0.0
        classification = {"step": step.id, "label": label, "confidence": confidence, "rationale": output.rationale[:500]}
        return {**update, "classification": classification, "audit_log": [audit(step.id, "classified", label=label, confidence=confidence)]}


async def assess(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        levels = _labels(step)
        names = [level["name"] for level in levels]
        dimension = step.dimension or "level"
        context = {"text": state["user_input"], "dimension": dimension, "levels": levels, "classification": state.get("classification")}
        try:
            output = await rt.structured("assess", step, context, AssessmentOutput)
            level = output.level if output.level in names else names[(len(names) - 1) // 2]
            rationale = output.rationale[:500]
        except ModelError as exc:
            level = names[(len(names) - 1) // 2]
            return {"assessments": {step.id: {"dimension": dimension, "level": level, "rationale": "model error"}}, **_model_failure(step.id, exc)}
        return {
            "assessments": {step.id: {"dimension": dimension, "level": level, "rationale": rationale}},
            "audit_log": [audit(step.id, "assessed", dimension=dimension, level=level)],
        }


async def retrieve(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        if rt.retriever is None:
            return {"audit_log": [audit(step.id, "skipped", reason="retrieval disabled")]}
        label = (state.get("classification") or {}).get("label", "")
        query = f"{state['user_input']} {label.replace('_', ' ')}".strip()
        try:
            result = await rt.retriever.search(
                query, sources=list(step.sources) or None, citation_offset=len(state.get("evidence", []))
            )
        except PermissionError as exc:
            return {"security_events": [{"type": "unapproved_source", "node": step.id, "detail": str(exc), "ts": now_iso()}], "audit_log": [audit(step.id, "denied")]}
        events = [
            {"type": "retrieved_injection", "node": step.id, "chunk": item["chunk"], "rules": item["rules"], "ts": now_iso()}
            for item in result.quarantined
        ]
        if events:
            GUARDRAIL_EVENTS.labels("retrieved_injection").inc(len(events))
        evidence = [item.as_dict() for item in result.evidence]
        return {
            "evidence": evidence,
            "security_events": events,
            "audit_log": [audit(step.id, "retrieved", citations=[e["citation"] for e in evidence], quarantined=len(events))],
        }


async def lookup(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        budget = blueprint.GUARDRAILS["max_tool_calls"] - state.get("tool_calls", 0)
        results: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        facts = gather_facts(state)
        for name in step.tools:
            if budget <= 0:
                results.append({"tool": name, "phase": "read", "ok": False, "arguments": {}, "data": None, "error": "tool-call budget exhausted", "quarantined": False})
                continue
            definition = rt.tools.get(name)
            context = {"text": state["user_input"], "tool": definition.describe(), "facts": facts}
            try:
                arguments = (await rt.structured("tool_arguments", step, context, ToolArgumentsOutput)).arguments
            except ModelError as exc:
                results.append({"tool": name, "phase": "read", "ok": False, "arguments": {}, "data": None, "error": f"argument selection failed: {exc}"[:300], "quarantined": False})
                continue
            outcome = (await rt.tools.invoke(name, arguments, phase="read", ctx=tool_context(state, "read"))).as_dict()
            budget -= 1
            if outcome["ok"] and outcome["data"] is not None:
                cleaned, rules = _quarantine_if_injected(outcome["data"])
                if rules:
                    outcome["data"], outcome["quarantined"] = cleaned, True
                    events.append({"type": "tool_output_injection", "node": step.id, "tool": name, "rules": rules, "ts": now_iso()})
            results.append(outcome)
        return {
            "tool_results": results,
            "tool_calls": len([r for r in results if r["error"] != "tool-call budget exhausted"]),
            "security_events": events,
            "audit_log": [audit(step.id, "tools_called", tools=[(r["tool"], r["ok"]) for r in results])],
        }


async def analyze(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        context = {
            "text": state["user_input"],
            "step": {"id": step.id, "description": step.description},
            "classification": state.get("classification"),
            "assessments": state.get("assessments"),
            "evidence": visible_evidence(state),
            "tool_results": visible_tool_results(state),
            "notes": state.get("notes"),
        }
        try:
            output = await rt.structured("analyze", step, context, AnalysisOutput)
        except ModelError as exc:
            return _model_failure(step.id, exc)
        return {"notes": {step.id: output.model_dump()}, "audit_log": [audit(step.id, "analyzed", findings=len(output.findings))]}


async def draft(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        tools = rt.tools.describe(step.tools)
        context = {
            "text": state["user_input"],
            "step": {"id": step.id, "description": step.description},
            "tools": tools,
            "facts": gather_facts(state),
            "classification": state.get("classification"),
            "assessments": state.get("assessments"),
            "evidence": visible_evidence(state),
            "tool_results": visible_tool_results(state),
            "notes": state.get("notes"),
            "history": recent_history(state),
        }
        try:
            output = await rt.structured("draft", step, context, DraftOutput)
        except ModelError as exc:
            return _model_failure(step.id, exc)
        actions: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        previews = 0
        existing = len(state.get("proposed_actions", []))
        for proposed in output.actions[: blueprint.GUARDRAILS["max_tool_calls"]]:
            if proposed.tool not in step.tools:
                events.append({"type": "tool_outside_step", "node": step.id, "tool": proposed.tool[:64], "ts": now_iso()})
                continue
            definition = rt.tools.get(proposed.tool)
            try:
                arguments = definition.validate(proposed.arguments)
            except ValidationError:
                events.append({"type": "invalid_proposal", "node": step.id, "tool": proposed.tool, "ts": now_iso()})
                continue
            preview: dict[str, Any] | None = None
            if definition.mode == ToolMode.DRAFT:
                result = await rt.tools.invoke(definition.name, arguments, phase="preview", ctx=tool_context(state, "preview"))
                previews += 1
                preview = result.data if result.ok else {"error": result.error}
            digest = action_digest(definition.name, arguments)
            actions.append(
                {
                    "id": f"act_{existing + len(actions) + 1}_{digest[:10]}",
                    "step": step.id,
                    "tool": definition.name,
                    "mode": str(definition.mode),
                    "arguments": arguments,
                    "preview": preview,
                    "rationale": proposed.rationale[:500],
                    "requires_approval": definition.approval_required,
                    "digest": digest,
                    "status": "proposed",
                }
            )
        return {
            "proposed_actions": actions,
            "draft_response": output.message or output.summary,
            "tool_calls": previews,
            "security_events": events,
            "audit_log": [audit(step.id, "proposed", actions=[a["tool"] for a in actions], rejected=len(events))],
        }


async def safety_check(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        findings = rt.policy.review(state.get("proposed_actions", []))
        if scan(state.get("draft_response", ""), profile="retrieved").suspicious:
            findings.append(
                PolicyFinding("instructions_in_draft", "block", "The draft response contains instruction-like content.")
            )
        blocking = [finding for finding in findings if finding.severity == "block"]
        if blocking:
            GUARDRAIL_EVENTS.labels("policy_violation").inc(len(blocking))
            return {
                "blocked": True,
                "block_reasons": ["Proposed actions violated the action policy."],
                "security_events": [
                    {"type": "policy_violation", "node": step.id, **finding.as_dict(), "ts": now_iso()}
                    for finding in blocking
                ],
                "audit_log": [audit(step.id, "blocked", rules=[finding.rule for finding in blocking])],
            }
        return {"audit_log": [audit(step.id, "passed", findings=[finding.rule for finding in findings])]}


async def verify(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        claims = [finding for note in (state.get("notes") or {}).values() for finding in note.get("findings", [])]
        if state.get("draft_response"):
            claims.append(state["draft_response"])
        evidence = visible_evidence(state)
        citations_required = blueprint.RETRIEVAL["citations_required"]
        context = {"claims": claims, "evidence": evidence, "citations_required": citations_required}
        try:
            output = await rt.structured("verify", step, context, VerificationOutput)
        except ModelError as exc:
            return _model_failure(step.id, exc)
        issues = list(output.issues)
        if citations_required and not evidence and "No evidence was retrieved to support the answer." not in issues:
            issues.append("No evidence was retrieved to support the answer.")
        if output.supported and not issues:
            return {"audit_log": [audit(step.id, "verified", claims=len(claims))]}
        return {
            "needs_review": True,
            "review_reasons": [issue[:300] for issue in issues[:10]] or ["Claims could not be verified."],
            "audit_log": [audit(step.id, "unverified", issues=len(issues))],
        }


async def human_approval(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    pending = [action for action in state.get("proposed_actions", []) if action.get("requires_approval")]
    review_needed = bool(state.get("needs_review")) or step.review == "always"
    if not pending and not review_needed:
        return {
            "approval": {"status": "not_required", "decided_at": now_iso()},
            "audit_log": [audit(step.id, "approval_not_required")],
        }
    request = {
        "type": "approval_request",
        "step": step.id,
        "actions": [
            {key: action[key] for key in ("id", "tool", "mode", "arguments", "preview", "rationale", "digest")}
            for action in pending
        ],
        "review_reasons": list(state.get("review_reasons", [])),
        "draft_response": state.get("draft_response", ""),
    }
    raw_decision = interrupt(request)
    try:
        decision = ApprovalDecision.model_validate(raw_decision)
    except ValidationError:
        decision = ApprovalDecision(approved=False, reviewer="system", comment="Invalid approval payload.")
    pending_ids = {action["id"] for action in pending}
    if decision.approved:
        chosen = set(decision.action_ids) if decision.action_ids is not None else pending_ids
        approved = [action for action in pending if action["id"] in chosen]
        approval = {
            "status": "approved",
            "approval_id": f"apr_{uuid.uuid4().hex[:16]}",
            "reviewer": decision.reviewer,
            "comment": decision.comment,
            "decided_at": now_iso(),
            "approved_action_ids": [action["id"] for action in approved],
            "approved_digests": [action["digest"] for action in approved],
        }
    else:
        approval = {
            "status": "rejected",
            "reviewer": decision.reviewer,
            "comment": decision.comment,
            "decided_at": now_iso(),
            "approved_action_ids": [],
            "approved_digests": [],
        }
    APPROVALS.labels(approval["status"]).inc()
    return {
        "approval": approval,
        "audit_log": [
            audit(
                step.id,
                f"approval_{approval['status']}",
                reviewer=decision.reviewer,
                approved=approval["approved_action_ids"],
                unknown_ids=sorted(set(decision.action_ids or []) - pending_ids),
            )
        ],
    }


async def execute(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        approval = state.get("approval") or {}
        approved_ids = set(approval.get("approved_action_ids", []))
        approved_digests = set(approval.get("approved_digests", []))
        results: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        for action in state.get("proposed_actions", []):
            entry = {"action_id": action["id"], "tool": action["tool"]}
            if action.get("requires_approval"):
                if approval.get("status") != "approved" or action["id"] not in approved_ids:
                    results.append({**entry, "status": "skipped", "reason": "not approved"})
                    continue
                current = action_digest(action["tool"], action["arguments"])
                if current != action["digest"] or current not in approved_digests:
                    events.append({"type": "approval_mismatch", "node": step.id, "action_id": action["id"], "ts": now_iso()})
                    results.append({**entry, "status": "skipped", "reason": "action changed after approval"})
                    continue
            outcome = await rt.tools.invoke(action["tool"], action["arguments"], phase="execute", ctx=tool_context(state, "execute"))
            results.append(
                {**entry, "status": "executed" if outcome.ok else "failed", "receipt": outcome.data, "error": outcome.error}
            )
        if events:
            GUARDRAIL_EVENTS.labels("approval_mismatch").inc(len(events))
        return {
            "executed_actions": results,
            "security_events": events,
            "audit_log": [audit(step.id, "executed", results=[(r["tool"], r["status"]) for r in results])],
        }


async def respond(rt: AgentRuntime, state: AgentState, step: StepConfig) -> dict[str, Any]:
    with timed(step.id):
        context = {
            "text": state["user_input"],
            "classification": state.get("classification"),
            "assessments": state.get("assessments"),
            "evidence": visible_evidence(state),
            "tool_results": visible_tool_results(state),
            "notes": state.get("notes"),
            "proposed_actions": [
                {"tool": a["tool"], "requires_approval": a["requires_approval"]} for a in state.get("proposed_actions", [])
            ],
            "executed_actions": state.get("executed_actions", []),
            "review_reasons": state.get("review_reasons", []),
            "draft_response": state.get("draft_response", ""),
            "history": recent_history(state),
        }
        try:
            output = await rt.structured("respond", step, context, ResponseOutput)
        except ModelError as exc:
            return {"final_response": state.get("draft_response", "Request processed."), **_model_failure(step.id, exc)}
        return {"final_response": output.response[:8000], "audit_log": [audit(step.id, "responded")]}
