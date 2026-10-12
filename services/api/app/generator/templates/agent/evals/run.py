"""Evaluation runner.

    python -m evals.run                      # offline, deterministic (CI / sandbox)
    python -m evals.run --live               # use the configured model provider
    python -m evals.run --report eval-report.json --category adversarial

Tools always run against the fixture backend so evaluations never touch real systems. The
process exits non-zero when any target in ``dataset.json`` is missed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from evals.graders import grade_safety, grade_task, grade_tools
from src.agent.contracts import ApprovalDecision
from src.agent.graph import build_graph
from src.agent.runtime import AgentRuntime
from src.agent.service import AgentService
from src.config import Settings
from src.observability import configure_logging
from src.tools.backends import FixtureBackend

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evals" / "dataset.json"


async def run_case(service: AgentService, backend: FixtureBackend, case: dict[str, Any]) -> dict[str, Any]:
    journal_start = len(backend.journal)
    started = time.perf_counter()
    outcome: dict[str, Any] = {"case_id": case["id"], "error": None}
    try:
        view = await service.start(case["input"], thread_id=f"eval-{case['id']}")
        first_status = view.status
        executed_before = len(backend.journal) - journal_start
        approval = case.get("approval")
        if view.status == "awaiting_approval" and approval is not None:
            decision = ApprovalDecision(
                approved=bool(approval.get("approved")),
                reviewer="evaluation-harness",
                action_ids=approval.get("action_ids"),
            )
            view = await service.resume(view.run_id, decision)
    except Exception as exc:  # recorded as a failed case, never crashes the suite
        outcome.update(
            first_status="error", status="error", classification=None, assessments={}, tools_called=[],
            proposed_tools=[], executed_tools=[], executed_before_approval=0, journal_tools=[],
            citations=0, citation_sources=[], response="", security_events=0,
            error=f"{type(exc).__name__}: {exc}"[:500],
        )
        outcome["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return outcome
    journal = backend.journal[journal_start:]
    outcome.update(
        first_status=first_status,
        status=view.status,
        classification=(view.classification or {}).get("label"),
        assessments={step: item.get("level") for step, item in view.assessments.items()},
        tools_called=sorted({result["tool"] for result in view.tool_results}),
        proposed_tools=sorted({action["tool"] for action in view.proposed_actions}),
        executed_tools=sorted(a["tool"] for a in view.executed_actions if a.get("status") == "executed"),
        executed_before_approval=executed_before,
        journal_tools=sorted(entry["tool"] for entry in journal),
        citations=len(view.citations),
        citation_sources=sorted({citation["source"] for citation in view.citations}),
        response=view.response or "",
        security_events=view.security_events,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return outcome


def grade_case(case: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    task = grade_task(case, outcome)
    tools = grade_tools(case, outcome)
    safety = grade_safety(case, outcome)
    return {
        "id": case["id"],
        "category": case["category"],
        "input": case["input"][:300],
        "passed": task.passed and safety.passed and (tools is None or tools.passed),
        "task": task.as_dict(),
        "tools": tools.as_dict() if tools else None,
        "safety": safety.as_dict(),
        "outcome": {key: outcome[key] for key in ("first_status", "status", "classification", "tools_called", "proposed_tools", "executed_tools", "citations", "duration_ms", "error")},
    }


def aggregate(results: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    total = len(results)
    task_passed = sum(1 for r in results if r["task"]["passed"])
    tp = sum(r["tools"]["counts"]["tp"] for r in results if r["tools"])
    fp = sum(r["tools"]["counts"]["fp"] for r in results if r["tools"])
    fn = sum(r["tools"]["counts"]["fn"] for r in results if r["tools"])
    tool_accuracy = 1.0 if tp + fp + fn == 0 else (2 * tp) / (2 * tp + fp + fn)
    unsafe = sum(r["safety"]["counts"]["unsafe_actions"] for r in results)
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"cases": 0, "passed": 0})
    for result in results:
        by_category[result["category"]]["cases"] += 1
        by_category[result["category"]]["passed"] += int(result["passed"])
    metrics = {
        "task_success": round(task_passed / total, 4) if total else 0.0,
        "tool_accuracy": round(tool_accuracy, 4),
        "unsafe_actions": unsafe,
        "cases": total,
        "passed_cases": sum(1 for r in results if r["passed"]),
    }
    checks = {
        "task_success": metrics["task_success"] >= thresholds["task_success"],
        "tool_accuracy": metrics["tool_accuracy"] >= thresholds["tool_accuracy"],
        "unsafe_actions": metrics["unsafe_actions"] <= thresholds["unsafe_actions"],
    }
    return {"metrics": metrics, "checks": checks, "passed": all(checks.values()), "by_category": dict(by_category)}


async def evaluate(dataset: dict[str, Any], *, live: bool, categories: set[str] | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agent-eval-", ignore_cleanup_errors=True) as scratch:
        overrides: dict[str, Any] = {
            "env": "test",
            "tool_backend": "fixture",
            "checkpoint_backend": "memory",
            "database_url": f"sqlite:///{Path(scratch) / 'eval-memory.db'}",
            "fixtures_path": ROOT / "data" / "fixtures" / "tools.json",
            "knowledge_dir": ROOT / "data" / "knowledge",
        }
        if not live:
            overrides.update(model_provider="offline", embeddings="hashing", vector_store="memory")
        settings = Settings(**overrides)
        backend = FixtureBackend(settings.fixtures_path)
        runtime = await AgentRuntime.create(settings, backend=backend)
        service = AgentService(runtime, build_graph(runtime))
        cases = [case for case in dataset["cases"] if not categories or case["category"] in categories]
        results = []
        for case in cases:
            outcome = await run_case(service, backend, case)
            results.append(grade_case(case, outcome))
    summary = aggregate(results, dataset["thresholds"])
    return {
        "schema": "agentforge.eval-report/v1",
        "agent": dataset.get("agent"),
        "mode": "live" if live else "offline",
        "model": runtime.model.name,
        "thresholds": dataset["thresholds"],
        **summary,
        "cases": results,
    }


def _print_summary(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    print(f"Evaluation ({report['mode']}, model={report['model']}): {metrics['passed_cases']}/{metrics['cases']} cases passed")
    for name, ok in report["checks"].items():
        target = report["thresholds"][name]
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<15} {metrics[name]!s:<8} target {'<=' if name == 'unsafe_actions' else '>='} {target}")
    for category, counts in sorted(report["by_category"].items()):
        print(f"  {category:<20} {counts['passed']}/{counts['cases']}")
    for result in report["cases"]:
        if not result["passed"]:
            problems = result["task"]["details"] + (result["tools"] or {}).get("details", []) + result["safety"]["details"]
            print(f"  ✗ {result['id']}: {'; '.join(problems)[:300]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent evaluation suite.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--live", action="store_true", help="use the configured model provider")
    parser.add_argument("--category", action="append", default=None)
    parser.add_argument("--verbose", action="store_true", help="show agent logs")
    args = parser.parse_args(argv)
    configure_logging("INFO" if args.verbose else "WARNING")
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    report = asyncio.run(evaluate(dataset, live=args.live, categories=set(args.category or []) or None))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _print_summary(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
