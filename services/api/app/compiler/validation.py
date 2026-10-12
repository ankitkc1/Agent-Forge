"""Validation and linting for user-authored AgentSpec documents (YAML or JSON)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from app.generator.shared.injection import scan
from app.schemas.agent_spec import AgentSpec

MAX_DOCUMENT_BYTES = 256_000


@dataclass(frozen=True)
class SpecIssue:
    loc: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"loc": self.loc, "message": self.message}


@dataclass
class ValidationOutcome:
    spec: AgentSpec | None
    errors: list[SpecIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.spec is not None and not self.errors


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of silently overwriting them."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key '{key}'", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,  # type: ignore[arg-type]
)


def parse_document(text: str) -> Any:
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError(f"specification exceeds {MAX_DOCUMENT_BYTES // 1000} KB")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return json.loads(text)
    return yaml.load(text, Loader=_UniqueKeyLoader)


def _format_loc(loc: tuple[Any, ...]) -> str:
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        elif item in {"function-after", "function-before", "function-wrap"} or str(item).startswith(
            ("function-", "tagged-union")
        ):
            continue
        else:
            parts.append(("." if parts else "") + str(item))
    return "".join(parts) or "$"


def _clean_message(message: str) -> str:
    return message.removeprefix("Value error, ")


def validate_document(document: Any) -> ValidationOutcome:
    """Validate a parsed document (dict) or raw YAML/JSON text."""
    if isinstance(document, str):
        try:
            document = parse_document(document)
        except (yaml.YAMLError, json.JSONDecodeError, ValueError) as exc:
            return ValidationOutcome(None, [SpecIssue("$", f"could not parse document: {exc}")])
    if not isinstance(document, dict):
        return ValidationOutcome(None, [SpecIssue("$", "specification must be a mapping/object")])
    try:
        spec = AgentSpec.model_validate(document)
    except ValidationError as exc:
        issues = [
            SpecIssue(_format_loc(tuple(error["loc"])), _clean_message(error["msg"]))
            for error in exc.errors(include_url=False)
        ]
        return ValidationOutcome(None, issues)
    return ValidationOutcome(spec, [], lint_spec(spec))


def lint_spec(spec: AgentSpec) -> list[str]:
    """Non-blocking findings that a reviewer should see before building."""
    warnings: list[str] = []
    kinds = [step.kind for step in spec.workflow]
    bound: set[str] = set()
    for step in spec.workflow:
        if step.kind == "lookup":
            bound.update(step.tools or [t.name for t in spec.tools if t.mode == "read"])
        if step.kind == "draft":
            bound.update(step.tools or [t.name for t in spec.tools if t.mode != "read"])
    for tool in spec.tools:
        if tool.name not in bound:
            warnings.append(f"Tool '{tool.name}' is declared but no workflow step can call it.")
        if tool.mode == "draft" and not spec.tool_requires_approval(tool):
            warnings.append(
                f"Draft tool '{tool.name}' will run without approval because both the tool and "
                "the external-message guardrail allow it."
            )
        if not tool.inputs:
            warnings.append(
                f"Tool '{tool.name}' declares no inputs; the generator will use a single "
                "free-text 'query' argument."
            )
    if any(tool.has_side_effects for tool in spec.tools) and "safety_check" not in kinds:
        warnings.append(
            "Side-effecting tools are declared but the workflow has no safety_check step; the "
            "platform guard still applies, but an explicit policy check is recommended."
        )
    for step in spec.workflow:
        if step.kind in {"classify", "assess"}:
            missing = [label.name for label in step.labels if not label.hints]
            if missing and len(missing) == len(step.labels):
                warnings.append(
                    f"Step '{step.id}' has no keyword hints on any label; offline evaluation will "
                    "fall back to label names only."
                )
    if spec.retrieval.enabled and "retrieve" not in kinds:
        warnings.append("Retrieval sources are declared but no retrieve step uses them.")
    if kinds[-1] != "respond":
        warnings.append(
            "The last workflow step is not a respond step; the runtime will compose a default answer."
        )
    if spec.model.temperature > 0.5:
        warnings.append(
            f"Model temperature {spec.model.temperature} reduces run-to-run reproducibility; "
            "≤ 0.3 is recommended for operational agents."
        )
    if spec.evaluation.unsafe_action_target > 0:
        warnings.append("The evaluation target tolerates unsafe actions; 0 is strongly recommended.")
    if spec.memory.pii_retention_days > 90:
        warnings.append(
            f"PII is retained for {spec.memory.pii_retention_days} days; confirm this matches your "
            "data-retention policy."
        )
    free_text = [
        ("agent.objective", spec.agent.objective),
        ("agent.description", spec.agent.description),
        *[(f"agent.constraints[{i}]", text) for i, text in enumerate(spec.agent.constraints)],
        *[(f"tools.{t.name}.description", t.description) for t in spec.tools],
        *[(f"workflow.{s.id}.description", s.description) for s in spec.workflow],
    ]
    for location, text in free_text:
        verdict = scan(text, profile="retrieved")
        if verdict.suspicious:
            warnings.append(
                f"{location} contains instruction-like text ({', '.join(verdict.rules)}); it will be "
                "rendered into prompts as data, but review it."
            )
    return warnings
