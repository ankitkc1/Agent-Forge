"""Action policy applied to proposed actions before they reach a human reviewer."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import ValidationError

from src.agent.contracts import action_digest
from src.guardrails.injection import scan
from src.tools.base import ToolMode, ToolNotAllowedError
from src.tools.registry import ToolRegistry

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("api_secret", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
)


@dataclass(frozen=True)
class PolicyFinding:
    rule: str
    severity: Literal["block", "review", "info"]
    message: str
    action_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


class ActionPolicy:
    def __init__(self, registry: ToolRegistry, *, max_actions: int = 8) -> None:
        self.registry = registry
        self.max_actions = max_actions

    def review(self, actions: Sequence[Mapping[str, Any]]) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        if len(actions) > self.max_actions:
            findings.append(
                PolicyFinding("too_many_actions", "block", f"{len(actions)} actions exceed the limit of {self.max_actions}.")
            )
        seen: set[str] = set()
        for action in actions:
            action_id = str(action.get("id"))
            tool = str(action.get("tool"))
            arguments = dict(action.get("arguments") or {})
            try:
                definition = self.registry.get(tool)
            except ToolNotAllowedError:
                findings.append(PolicyFinding("tool_not_allowlisted", "block", f"{tool} is not allowlisted.", action_id))
                continue
            if definition.mode == ToolMode.READ:
                findings.append(PolicyFinding("read_tool_proposed", "block", f"{tool} is read-only and cannot be an action.", action_id))
            try:
                normalized = definition.validate(arguments)
            except ValidationError:
                findings.append(PolicyFinding("invalid_arguments", "block", f"Arguments for {tool} failed validation.", action_id))
                continue
            if action_digest(tool, normalized) != action.get("digest"):
                findings.append(PolicyFinding("digest_mismatch", "block", f"Action {action_id} changed after it was proposed.", action_id))
            if action.get("digest") in seen:
                findings.append(PolicyFinding("duplicate_action", "info", f"Duplicate proposal for {tool}.", action_id))
            seen.add(str(action.get("digest")))
            for text in _strings(arguments):
                verdict = scan(text, profile="retrieved")
                if verdict.suspicious:
                    findings.append(
                        PolicyFinding(
                            "instructions_in_arguments",
                            "block",
                            f"{tool} arguments contain instruction-like content ({', '.join(verdict.rules)}).",
                            action_id,
                        )
                    )
                    break
                for name, pattern in SECRET_PATTERNS:
                    if pattern.search(text):
                        findings.append(PolicyFinding("secret_in_arguments", "block", f"{tool} arguments contain a {name}.", action_id))
        return findings
