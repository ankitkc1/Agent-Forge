"""Risk analysis: a reviewable risk register derived from the spec and the verified topology.

Findings are classified by severity and status. ``open`` findings are unresolved, ``accepted``
findings are deliberate configuration choices the owner should acknowledge, and ``mitigated``
findings are covered by a verified control. Critical findings block the build.
"""

from __future__ import annotations

from app.schemas.agent_spec import AgentSpec
from app.schemas.plan import SEVERITY_ORDER, RiskFinding, RiskReport, ToolBinding, TopologyCheck


def assess_risk(spec: AgentSpec, checks: list[TopologyCheck], tools: list[ToolBinding]) -> RiskReport:
    findings: list[RiskFinding] = []
    checks_by_id = {check.id: check for check in checks}

    for check in checks:
        if not check.passed:
            findings.append(
                RiskFinding(
                    id=f"TOPOLOGY-{check.id.upper()}",
                    severity="critical",
                    title=f"Topology check failed: {check.title}",
                    detail=check.detail,
                    mitigation="Fix the workflow so the generated graph satisfies the invariant.",
                    status="open",
                    blocking=True,
                )
            )

    side_effect_tools = [tool for tool in tools if tool.mode != "read"]
    if side_effect_tools:
        gate = checks_by_id.get("approval_dominates_side_effects")
        findings.append(
            RiskFinding(
                id="ACTIONS-EXTERNAL-SIDE-EFFECTS",
                severity="high",
                title="Agent can change external systems",
                detail="Side-effecting tools: "
                + ", ".join(f"{tool.name} ({tool.mode})" for tool in side_effect_tools),
                mitigation=(
                    "Actions are proposals until a reviewer approves them; approvals bind to the "
                    "exact tool arguments (SHA-256 digest) and are re-verified before execution."
                ),
                status="mitigated" if gate and gate.passed else "open",
                blocking=not (gate and gate.passed),
            )
        )
        if len([tool for tool in side_effect_tools if tool.mode == "execute"]) > 5:
            findings.append(
                RiskFinding(
                    id="ACTIONS-BROAD-SURFACE",
                    severity="medium",
                    title="Broad action surface",
                    detail="More than five execute-mode tools increase blast radius.",
                    mitigation="Split the agent or move rarely used actions to a separate workflow.",
                    status="accepted",
                )
            )
    unapproved_drafts = [tool.name for tool in tools if tool.mode == "draft" and not tool.approval_required]
    if unapproved_drafts:
        findings.append(
            RiskFinding(
                id="ACTIONS-UNAPPROVED-DRAFTS",
                severity="medium",
                title="Draft tools commit without approval",
                detail=f"{', '.join(unapproved_drafts)} execute without a human decision.",
                mitigation="Set approval_required: true or guardrails.external_messages.approval_required.",
                status="accepted",
            )
        )
    kinds = [step.kind for step in spec.workflow]
    if side_effect_tools and "safety_check" not in kinds:
        findings.append(
            RiskFinding(
                id="POLICY-NO-SAFETY-STEP",
                severity="medium",
                title="No explicit safety_check step",
                detail="Proposed actions are not policy-checked before approval.",
                mitigation="Add a safety_check step between draft and human_approval.",
                status="accepted",
            )
        )

    if spec.retrieval.enabled:
        scanned = spec.guardrails.prompt_injection.scan_retrieved_content
        findings.append(
            RiskFinding(
                id="RAG-INDIRECT-INJECTION",
                severity="high",
                title="Retrieved documents can carry indirect prompt injection",
                detail=f"Sources: {', '.join(spec.retrieval.source_names)}.",
                mitigation=(
                    "Retrieved chunks are scanned and quarantined when they contain instructions; "
                    "evidence is framed as data and cannot trigger tools directly."
                    if scanned
                    else "Enable guardrails.prompt_injection.scan_retrieved_content."
                ),
                status="mitigated" if scanned else "open",
            )
        )
    findings.append(
        RiskFinding(
            id="INPUT-PROMPT-INJECTION",
            severity="high",
            title="Untrusted user input",
            detail=f"Policy on detection: {spec.guardrails.prompt_injection.action}.",
            mitigation=(
                "The input guard runs before any model call; suspicious requests are blocked and logged."
                if spec.guardrails.prompt_injection.action == "block_and_log"
                else "Suspicious requests are routed to human review before any action executes."
            ),
            status="mitigated",
        )
    )

    if spec.model.provider in {"openai", "anthropic"}:
        findings.append(
            RiskFinding(
                id="DATA-THIRD-PARTY-MODEL",
                severity="low",
                title="Prompts leave the trust boundary",
                detail=(f"Requests, retrieved evidence and tool results are sent to {spec.model.provider}."),
                mitigation="Confirm the provider's data-processing terms; use provider='local' for strict residency.",
                status="accepted",
            )
        )
    if spec.memory.type != "none":
        long_retention = spec.memory.pii_retention_days > 90
        findings.append(
            RiskFinding(
                id="DATA-PII-RETENTION",
                severity="medium" if long_retention else "low",
                title="Conversation memory stores personal data",
                detail=f"{spec.memory.pii_retention_days}-day retention in namespace '{spec.memory.namespace}'.",
                mitigation=(
                    "PII is redacted before persistence"
                    if spec.guardrails.pii.redact_memory
                    else "Enable guardrails.pii.redact_memory"
                )
                + "; expired records are purged and threads can be erased on request.",
                status="mitigated"
                if spec.guardrails.pii.redact_memory and not long_retention
                else "accepted",
            )
        )
    if spec.evaluation.unsafe_action_target > 0:
        findings.append(
            RiskFinding(
                id="EVAL-UNSAFE-TOLERANCE",
                severity="high",
                title="Evaluation tolerates unsafe actions",
                detail=f"unsafe_action_target = {spec.evaluation.unsafe_action_target}.",
                mitigation="Set evaluation.unsafe_action_target to 0.",
                status="open",
            )
        )
    slow = [tool.name for tool in tools if tool.timeout_seconds > 120]
    if slow:
        findings.append(
            RiskFinding(
                id="RELIABILITY-LONG-TIMEOUTS",
                severity="low",
                title="Long tool timeouts",
                detail=f"{', '.join(slow)} may block a run for over two minutes.",
                mitigation="Prefer asynchronous patterns for long-running integrations.",
                status="accepted",
            )
        )
    if spec.model.temperature > 0.5:
        findings.append(
            RiskFinding(
                id="RELIABILITY-NONDETERMINISM",
                severity="low",
                title="High sampling temperature",
                detail=f"temperature = {spec.model.temperature}.",
                mitigation="Use ≤ 0.3 for operational agents.",
                status="accepted",
            )
        )

    considered = [finding for finding in findings if finding.status != "mitigated"]
    level = max((finding.severity for finding in considered), key=SEVERITY_ORDER.__getitem__, default="low")
    return RiskReport(
        level=level,
        blocking=any(finding.blocking for finding in findings),
        findings=sorted(findings, key=lambda finding: -SEVERITY_ORDER[finding.severity]),
    )
