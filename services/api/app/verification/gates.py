"""Quality gates executed inside the sandbox. Every metric is parsed from real tool output."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from app.sandbox import OUTPUT_DIR, CommandResult, SandboxRunner
from app.schemas.report import CommandSummary, GateResult, SecurityFinding
from app.verification.reports import (
    ArtefactError,
    parse_bandit,
    parse_coverage,
    parse_eval_report,
    parse_junit,
)

SYNTAX_CHECK = (
    "import pathlib, sys\n"
    "errors = []\n"
    "for path in sorted(pathlib.Path('.').rglob('*.py')):\n"
    "    if any(part.startswith('.') for part in path.parts):\n"
    "        continue\n"
    "    try:\n"
    "        compile(path.read_text(encoding='utf-8'), str(path), 'exec')\n"
    "    except SyntaxError as exc:\n"
    "        errors.append(f'{path}:{exc.lineno}: {exc.msg}')\n"
    "print('\\n'.join(errors) or 'syntax ok')\n"
    "sys.exit(1 if errors else 0)\n"
)
QUALITY_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python", "-c", SYNTAX_CHECK),
    ("python", "-m", "ruff", "check", "--no-cache", "--output-format", "concise", "."),
    ("python", "-m", "ruff", "format", "--no-cache", "--check", "."),
)
JUNIT = f"{OUTPUT_DIR}/junit.xml"
COVERAGE = f"{OUTPUT_DIR}/coverage.json"
EVAL_REPORT = f"{OUTPUT_DIR}/eval-report.json"
BANDIT_REPORT = f"{OUTPUT_DIR}/bandit.json"
TEST_COMMAND = (
    "python",
    "-m",
    "pytest",
    "-q",
    "-p",
    "no:cacheprovider",
    f"--junitxml={JUNIT}",
    "--cov=src",
    f"--cov-report=json:{COVERAGE}",
    "--cov-report=term",
)
EVAL_COMMAND = ("python", "-m", "evals.run", "--report", EVAL_REPORT)
BANDIT_COMMAND = ("python", "-m", "bandit", "-q", "-r", "src", "mcp", "-f", "json", "-o", BANDIT_REPORT)


def _summary(result: CommandResult) -> CommandSummary:
    data = result.as_dict()
    return CommandSummary(
        command=str(data["command"])[:200],
        exit_code=result.exit_code,
        duration_seconds=round(result.duration_seconds, 3),
        timed_out=result.timed_out,
        output_tail=result.tail(80)[-8000:],
    )


def _prepare(workspace: Path) -> None:
    (workspace / OUTPUT_DIR).mkdir(exist_ok=True)


def run_quality_gate(
    sandbox: SandboxRunner, workspace: Path, *, should_cancel: Callable[[], bool] | None = None
) -> GateResult:
    _prepare(workspace)
    started = time.perf_counter()
    commands: list[CommandSummary] = []
    for argv in QUALITY_COMMANDS:
        result = sandbox.run(workspace, argv, should_cancel=should_cancel)
        commands.append(_summary(result))
        if not result.ok:
            label = "syntax check" if argv[1] == "-c" else " ".join(argv[2:4])
            return GateResult(
                name="quality",
                status="failed",
                duration_seconds=round(time.perf_counter() - started, 3),
                summary=f"{label} failed",
                commands=commands,
            )
    return GateResult(
        name="quality",
        status="passed",
        duration_seconds=round(time.perf_counter() - started, 3),
        summary="syntax, lint and formatting checks passed",
        commands=commands,
    )


def run_test_gate(
    sandbox: SandboxRunner, workspace: Path, *, should_cancel: Callable[[], bool] | None = None
) -> GateResult:
    _prepare(workspace)
    for artefact in (JUNIT, COVERAGE):
        (workspace / artefact).unlink(missing_ok=True)
    started = time.perf_counter()
    result = sandbox.run(workspace, TEST_COMMAND, collect=(JUNIT, COVERAGE), should_cancel=should_cancel)
    gate = GateResult(name="tests", status="passed", commands=[_summary(result)])
    try:
        gate.tests, gate.test_cases = parse_junit(workspace / JUNIT)
    except (ArtefactError, ValueError) as exc:
        gate.status = "error"
        gate.summary = f"pytest produced no readable report: {exc}"
    try:
        gate.coverage = parse_coverage(workspace / COVERAGE)
    except (ArtefactError, ValueError, KeyError):
        gate.coverage = None
    if gate.status != "error":
        tests = gate.tests
        assert tests is not None
        failed = tests.failed + tests.errors
        if result.timed_out or not result.ok or failed:
            gate.status = "failed"
            gate.summary = (
                "pytest timed out" if result.timed_out else f"{failed} of {tests.total} tests failed"
            )
        else:
            coverage = f", coverage {gate.coverage.percent:.1f}%" if gate.coverage else ""
            gate.summary = f"{tests.passed} passed, {tests.skipped} skipped{coverage}"
    gate.duration_seconds = round(time.perf_counter() - started, 3)
    return gate


def run_evaluation_gate(
    sandbox: SandboxRunner,
    workspace: Path,
    *,
    enforce: bool = True,
    should_cancel: Callable[[], bool] | None = None,
) -> GateResult:
    _prepare(workspace)
    (workspace / EVAL_REPORT).unlink(missing_ok=True)
    started = time.perf_counter()
    result = sandbox.run(workspace, EVAL_COMMAND, collect=(EVAL_REPORT,), should_cancel=should_cancel)
    gate = GateResult(name="evaluation", status="passed", commands=[_summary(result)])
    try:
        gate.evaluation = parse_eval_report(workspace / EVAL_REPORT)
    except (ArtefactError, ValueError, KeyError) as exc:
        gate.status = "error"
        gate.summary = f"evaluation produced no readable report: {exc}"
        gate.duration_seconds = round(time.perf_counter() - started, 3)
        return gate
    evaluation = gate.evaluation
    gate.summary = (
        f"{evaluation.passed_cases}/{evaluation.cases} cases · task {evaluation.task_success:.1%} · "
        f"tools {evaluation.tool_accuracy:.1%} · unsafe {evaluation.unsafe_actions}"
    )
    if not evaluation.passed:
        gate.status = "failed" if enforce else "warning"
        gate.summary += " · targets missed" + ("" if enforce else " (not enforced)")
    if result.timed_out:
        gate.status = "failed"
        gate.summary = "evaluation timed out"
    gate.duration_seconds = round(time.perf_counter() - started, 3)
    return gate


def run_bandit(
    sandbox: SandboxRunner, workspace: Path, *, should_cancel: Callable[[], bool] | None = None
) -> tuple[list[SecurityFinding], CommandSummary | None]:
    _prepare(workspace)
    (workspace / BANDIT_REPORT).unlink(missing_ok=True)
    result = sandbox.run(workspace, BANDIT_COMMAND, collect=(BANDIT_REPORT,), should_cancel=should_cancel)
    try:
        issues = parse_bandit(workspace / BANDIT_REPORT)
    except (ArtefactError, ValueError):
        return [], _summary(result)
    findings = []
    for issue in issues:
        severity = str(issue.get("issue_severity", "LOW")).lower()
        confidence = str(issue.get("issue_confidence", "LOW")).lower()
        mapped = {"high": "high", "medium": "medium", "low": "low"}.get(severity, "low")
        if confidence == "low" and mapped != "low":
            mapped = "low" if mapped == "medium" else "medium"
        findings.append(
            SecurityFinding(
                rule_id=f"BANDIT-{issue.get('test_id', 'B000')}",
                severity=mapped,  # type: ignore[arg-type]
                title=str(issue.get("test_name", "bandit finding")),
                path=str(issue.get("filename", "")).removeprefix("./") or None,
                line=int(issue.get("line_number") or 0) or None,
                detail=str(issue.get("issue_text", ""))[:500],
                source="bandit",
                blocking=mapped in {"high", "critical"},
            )
        )
    return findings, _summary(result)
