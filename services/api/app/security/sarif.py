"""SARIF 2.1.0 export so findings can be uploaded to GitHub code scanning or other tools."""

from __future__ import annotations

from typing import Any

from app.schemas.report import SecurityReport

LEVELS = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "info": "note"}


def to_sarif(report: SecurityReport, *, tool_version: str) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    results = []
    for finding in report.findings:
        rules.setdefault(
            finding.rule_id,
            {
                "id": finding.rule_id,
                "shortDescription": {"text": finding.title[:200]},
                "properties": {
                    "security-severity": {
                        "critical": "9.5",
                        "high": "8.0",
                        "medium": "5.5",
                        "low": "3.0",
                        "info": "1.0",
                    }[finding.severity]
                },
            },
        )
        result: dict[str, Any] = {
            "ruleId": finding.rule_id,
            "level": LEVELS[finding.severity],
            "message": {"text": f"{finding.title}. {finding.detail}".strip()},
            "properties": {"source": finding.source, "blocking": finding.blocking},
        }
        if finding.path:
            location: dict[str, Any] = {"artifactLocation": {"uri": finding.path}}
            if finding.line:
                location["region"] = {"startLine": finding.line}
            result["locations"] = [{"physicalLocation": location}]
        results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "AgentForge security validation",
                        "version": tool_version,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }
