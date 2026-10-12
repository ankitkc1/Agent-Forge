"""Parsers for artefacts produced inside the sandbox (JUnit XML, coverage JSON, eval/bandit JSON).

Artefacts are treated as untrusted input: sizes are capped and XML is parsed with defusedxml.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from defusedxml import ElementTree

from app.schemas.report import (
    CoverageFile,
    CoverageSummary,
    EvalCaseResult,
    EvalSummary,
    TestCaseResult,
    TestSummary,
)

MAX_ARTEFACT_BYTES = 20_000_000


class ArtefactError(ValueError):
    pass


def _read(path: Path) -> bytes:
    if not path.is_file():
        raise ArtefactError(f"missing artefact: {path.name}")
    if path.stat().st_size > MAX_ARTEFACT_BYTES:
        raise ArtefactError(f"artefact too large: {path.name}")
    return path.read_bytes()


def parse_junit(path: Path) -> tuple[TestSummary, list[TestCaseResult]]:
    root = ElementTree.fromstring(_read(path))
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    summary = TestSummary()
    cases: list[TestCaseResult] = []
    for suite in suites:
        summary.duration_seconds += float(suite.get("time", 0) or 0)
        for case in suite.iter("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "")
            identifier = f"{classname.replace('.', '/')}.py::{name}" if classname else name
            outcome = "passed"
            message = None
            for tag in ("failure", "error", "skipped"):
                element = case.find(tag)
                if element is not None:
                    outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                    message = (element.get("message") or element.text or "")[:500] or None
                    break
            cases.append(
                TestCaseResult(
                    id=identifier[:300],
                    outcome=outcome,  # type: ignore[arg-type]
                    duration_seconds=float(case.get("time", 0) or 0),
                    message=message,
                )
            )
    summary.total = len(cases)
    summary.passed = sum(case.outcome == "passed" for case in cases)
    summary.failed = sum(case.outcome == "failed" for case in cases)
    summary.errors = sum(case.outcome == "error" for case in cases)
    summary.skipped = sum(case.outcome == "skipped" for case in cases)
    summary.duration_seconds = round(summary.duration_seconds, 3)
    return summary, cases


def parse_coverage(path: Path) -> CoverageSummary:
    data: dict[str, Any] = json.loads(_read(path))
    totals = data.get("totals", {})
    files = [
        CoverageFile(
            path=name,
            percent=round(float(details["summary"].get("percent_covered", 0.0)), 2),
            missing_lines=int(details["summary"].get("missing_lines", 0)),
        )
        for name, details in sorted(data.get("files", {}).items())
    ]
    return CoverageSummary(
        percent=round(float(totals.get("percent_covered", 0.0)), 2),
        covered_lines=int(totals.get("covered_lines", 0)),
        total_lines=int(totals.get("num_statements", 0)),
        files=files,
    )


def parse_eval_report(path: Path) -> EvalSummary:
    data: dict[str, Any] = json.loads(_read(path))
    metrics = data["metrics"]
    case_results = []
    for case in data.get("cases", []):
        details = list(case.get("task", {}).get("details", []))
        details += list((case.get("tools") or {}).get("details", []))
        details += list(case.get("safety", {}).get("details", []))
        case_results.append(
            EvalCaseResult(
                id=str(case["id"]),
                category=str(case["category"]),
                passed=bool(case["passed"]),
                details=details[:10],
            )
        )
    return EvalSummary(
        mode=str(data.get("mode", "offline")),
        model=str(data.get("model", "unknown")),
        passed=bool(data.get("passed")),
        task_success=float(metrics["task_success"]),
        tool_accuracy=float(metrics["tool_accuracy"]),
        unsafe_actions=int(metrics["unsafe_actions"]),
        cases=int(metrics["cases"]),
        passed_cases=int(metrics["passed_cases"]),
        thresholds={key: float(value) for key, value in data.get("thresholds", {}).items()},
        by_category=data.get("by_category", {}),
        case_results=case_results,
    )


def parse_bandit(path: Path) -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(_read(path))
    return list(data.get("results", []))
