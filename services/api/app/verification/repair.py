"""Repair agent: bounded, auditable fixes for failed quality gates.

Strategies, in order:

1. **Mechanical** (quality gate): ``ruff check --fix`` and ``ruff format`` inside the sandbox.
   Semantics-preserving fixes only.
2. **LLM patch** (optional, ``AGENTFORGE_REPAIR_USE_LLM=true``): the model receives the failing
   output and the implicated source files and returns full replacements for files under ``src/``.
   Tests, evaluation data and graders can never be modified — a repair must make the agent pass
   the suite, not weaken it. Every replacement must parse, must pass the security scanner's AST
   rules, and is recorded with a diff summary.

A repair that changes nothing ends the loop; the build then fails with the original evidence.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.llm.client import JsonLLM, LLMError
from app.sandbox import SandboxRunner
from app.schemas.report import GateResult, RepairAttemptReport
from app.security.scanner import python_findings

MAX_CONTEXT_FILES = 4
MAX_FILE_CHARS = 20_000
_PATH_PATTERN = re.compile(r"((?:src|tests|evals|mcp)/[\w/.-]+\.py)")
REPAIRABLE_PREFIX = "src/"

REPAIR_SYSTEM_PROMPT = """You repair a generated Python repository so its failing checks pass.
Return JSON: {"files": [{"path": "src/...py", "content": "<complete new file>"}], "explanation": "..."}
Rules: only modify files under src/; never modify tests, evaluation data or graders; keep public
interfaces stable; do not add dependencies, network calls, subprocesses, eval/exec or file-system
access outside the repository. Output complete files, not diffs."""


def _digest_tree(workspace: Path) -> dict[str, str]:
    digests = {}
    for path in workspace.rglob("*.py"):
        relative = path.relative_to(workspace).as_posix()
        if relative.startswith("."):
            continue
        digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


@dataclass
class RepairAgent:
    sandbox: SandboxRunner
    llm: JsonLLM | None = None

    def repair(self, workspace: Path, failure: GateResult, attempt: int) -> RepairAttemptReport:
        if failure.name == "quality":
            report = self._mechanical(workspace, failure, attempt)
            if report.outcome == "changed" or self.llm is None:
                return report
        if self.llm is not None:
            return self._llm_patch(workspace, failure, attempt)
        return RepairAttemptReport(
            number=attempt,
            gate=failure.name,
            strategy="none",
            outcome="unchanged",
            detail="No automatic strategy applies; enable AGENTFORGE_REPAIR_USE_LLM for model-assisted repair.",
        )

    def _mechanical(self, workspace: Path, failure: GateResult, attempt: int) -> RepairAttemptReport:
        before = _digest_tree(workspace)
        outputs = []
        for argv in (
            ("python", "-m", "ruff", "check", "--no-cache", "--fix", "."),
            ("python", "-m", "ruff", "format", "--no-cache", "."),
        ):
            result = self.sandbox.run(workspace, argv)
            outputs.append(result.tail(10))
        changed = _changed(before, _digest_tree(workspace))
        return RepairAttemptReport(
            number=attempt,
            gate=failure.name,
            strategy="ruff --fix + ruff format",
            outcome="changed" if changed else "unchanged",
            changed_files=changed,
            detail="\n".join(outputs)[-1500:],
        )

    def _implicated_files(self, workspace: Path, failure: GateResult) -> list[str]:
        text = "\n".join(command.output_tail for command in failure.commands)
        text += "\n".join(case.message or "" for case in failure.test_cases if case.outcome != "passed")
        found: list[str] = []
        for match in _PATH_PATTERN.finditer(text):
            path = match.group(1)
            if path.startswith(REPAIRABLE_PREFIX) and path not in found and (workspace / path).is_file():
                found.append(path)
        return found[:MAX_CONTEXT_FILES]

    def _llm_patch(self, workspace: Path, failure: GateResult, attempt: int) -> RepairAttemptReport:
        assert self.llm is not None
        files = self._implicated_files(workspace, failure)
        if not files:
            return RepairAttemptReport(
                number=attempt,
                gate=failure.name,
                strategy="llm-patch",
                outcome="unchanged",
                detail="The failure output does not implicate any file under src/.",
            )
        context = "\n\n".join(
            f"### {path}\n```python\n{(workspace / path).read_text(encoding='utf-8')[:MAX_FILE_CHARS]}\n```"
            for path in files
        )
        failure_text = "\n".join(command.output_tail for command in failure.commands)[-6000:]
        prompt = f"Failing gate: {failure.name}\n\nOutput:\n{failure_text}\n\nFiles:\n{context}"
        try:
            response = self.llm.complete_json(REPAIR_SYSTEM_PROMPT, prompt, max_tokens=8000)
        except LLMError as exc:
            return RepairAttemptReport(
                number=attempt,
                gate=failure.name,
                strategy="llm-patch",
                outcome="error",
                detail=str(exc)[:500],
            )
        replacements = response.get("files", []) if isinstance(response, dict) else []
        accepted: list[tuple[str, str]] = []
        for item in replacements[:MAX_CONTEXT_FILES]:
            if not isinstance(item, dict):
                continue
            path, content = str(item.get("path", "")), item.get("content")
            pure = PurePosixPath(path)
            if not isinstance(content, str) or pure.is_absolute() or ".." in pure.parts:
                continue
            if (
                not path.startswith(REPAIRABLE_PREFIX)
                or not path.endswith(".py")
                or not (workspace / path).is_file()
            ):
                continue
            try:
                ast.parse(content)
            except SyntaxError:
                continue
            if any(finding.blocking for finding in python_findings(path, content)):
                return RepairAttemptReport(
                    number=attempt,
                    gate=failure.name,
                    strategy="llm-patch",
                    outcome="rejected",
                    detail=f"Proposed change to {path} violates the security policy.",
                )
            accepted.append((path, content))
        if not accepted:
            return RepairAttemptReport(
                number=attempt,
                gate=failure.name,
                strategy="llm-patch",
                outcome="unchanged",
                detail="No acceptable file replacements were proposed.",
            )
        before = _digest_tree(workspace)
        for path, content in accepted:
            (workspace / path).write_text(content, encoding="utf-8")
        return RepairAttemptReport(
            number=attempt,
            gate=failure.name,
            strategy="llm-patch",
            outcome="changed",
            changed_files=_changed(before, _digest_tree(workspace)),
            detail=str(response.get("explanation", ""))[:1000],
        )
