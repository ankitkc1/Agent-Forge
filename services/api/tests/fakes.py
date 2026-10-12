"""Test doubles: a scripted sandbox that fabricates gate artefacts *only for tests*."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.sandbox.base import CommandResult

JUNIT_PASS = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="0" errors="0" skipped="1" time="1.25">
<testcase classname="tests.unit.test_tools" name="test_a" time="0.1"/>
<testcase classname="tests.unit.test_tools" name="test_b" time="0.2"/>
<testcase classname="tests.agent.test_flow" name="test_c" time="0.3"><skipped message="not applicable"/></testcase>
</testsuite></testsuites>"""
JUNIT_FAIL = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0" time="0.5">
<testcase classname="tests.unit.test_tools" name="test_a" time="0.1"/>
<testcase classname="tests.unit.test_tools" name="test_b" time="0.2"><failure message="assert 1 == 2">src/agent/patterns.py:10: AssertionError</failure></testcase>
</testsuite></testsuites>"""
COVERAGE = {
    "totals": {"percent_covered": 87.5, "covered_lines": 700, "num_statements": 800},
    "files": {"src/a.py": {"summary": {"percent_covered": 90.0, "missing_lines": 3}}},
}


def eval_report(passed: bool = True) -> dict:
    return {
        "mode": "offline",
        "model": "offline",
        "passed": passed,
        "metrics": {
            "task_success": 1.0 if passed else 0.5,
            "tool_accuracy": 1.0,
            "unsafe_actions": 0 if passed else 1,
            "cases": 4,
            "passed_cases": 4 if passed else 2,
        },
        "thresholds": {"task_success": 0.9, "tool_accuracy": 0.95, "unsafe_actions": 0},
        "by_category": {
            "functional": {"cases": 2, "passed": 2},
            "adversarial": {"cases": 2, "passed": 2 if passed else 0},
        },
        "cases": [
            {
                "id": "functional-1",
                "category": "functional",
                "passed": True,
                "task": {"details": []},
                "tools": None,
                "safety": {"details": []},
            },
            {
                "id": "adversarial-1",
                "category": "adversarial",
                "passed": passed,
                "task": {"details": []},
                "tools": None,
                "safety": {"details": [] if passed else ["executed without approval"]},
            },
        ],
    }


@dataclass
class ScriptedSandbox:
    """Responds to gate commands by name. ``fail`` maps a gate keyword to remaining failures."""

    name: str = "scripted"
    available: bool = True
    fail: dict[str, int] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    on_command: Callable[[Path, list[str]], None] | None = None

    def check(self) -> tuple[bool, str]:
        return (True, "scripted sandbox") if self.available else (False, "sandbox runtime missing")

    def _should_fail(self, key: str) -> bool:
        remaining = self.fail.get(key, 0)
        if remaining > 0:
            self.fail[key] = remaining - 1
            return True
        return False

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout: int | None = None,
        collect: Sequence[str] = (),
        should_cancel=None,
    ) -> CommandResult:  # type: ignore[no-untyped-def]
        command = list(argv)
        self.calls.append(command)
        if self.on_command:
            self.on_command(workspace, command)
        out = workspace / ".agentforge-out"
        out.mkdir(exist_ok=True)
        joined = " ".join(command)
        if "ruff check" in joined and "--fix" not in joined:
            failed = self._should_fail("lint")
            return CommandResult(
                command,
                1 if failed else 0,
                "src/agent/x.py:1:1: F401 unused import" if failed else "All checks passed!",
                0.1,
            )
        if "pytest" in joined:
            failed = self._should_fail("tests")
            (out / "junit.xml").write_text(JUNIT_FAIL if failed else JUNIT_PASS)
            (out / "coverage.json").write_text(json.dumps(COVERAGE))
            return CommandResult(
                command, 1 if failed else 0, "1 failed" if failed else "2 passed, 1 skipped", 1.0
            )
        if "evals.run" in joined:
            failed = self._should_fail("evals")
            (out / "eval-report.json").write_text(json.dumps(eval_report(not failed)))
            return CommandResult(command, 1 if failed else 0, "Evaluation", 0.5)
        if "bandit" in joined:
            (out / "bandit.json").write_text(json.dumps({"results": []}))
            return CommandResult(command, 0, "", 0.2)
        return CommandResult(command, 0, "ok", 0.05)


@dataclass
class FakeLLM:
    responses: list[dict]
    name: str = "fake"
    model: str = "fake-model"
    prompts: list[tuple[str, str]] = field(default_factory=list)

    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict:
        self.prompts.append((system, user))
        if not self.responses:
            raise AssertionError("FakeLLM has no response left")
        return self.responses.pop(0)
