"""Tool primitives: modes, phases, typed definitions and results.

Phases enforce *when* a tool may run:

* ``read``    - read-only lookups (mode ``read``) during the workflow.
* ``preview`` - side-effect-free drafts (mode ``draft``) while proposing actions.
* ``execute`` - side effects (modes ``draft`` and ``execute``), only from the execute node and
  only for actions whose approval digest matches.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Phase = Literal["read", "preview", "execute"]


class ToolMode(StrEnum):
    READ = "read"
    DRAFT = "draft"
    EXECUTE = "execute"


ALLOWED_PHASES: dict[ToolMode, frozenset[str]] = {
    ToolMode.READ: frozenset({"read"}),
    ToolMode.DRAFT: frozenset({"preview", "execute"}),
    ToolMode.EXECUTE: frozenset({"execute"}),
}


class ToolError(Exception):
    """Base class for tool failures surfaced to the agent as failed results."""


class ToolNotAllowedError(ToolError, PermissionError):
    pass


class ToolPhaseError(ToolError, PermissionError):
    pass


class ToolInputError(ToolError, ValueError):
    pass


class ToolTimeoutError(ToolError, TimeoutError):
    pass


class ToolBudgetError(ToolError):
    pass


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    thread_id: str
    request_id: str
    phase: Phase


class ToolBackend(Protocol):
    async def call(
        self, tool: str, phase: Phase, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]: ...


Handler = Callable[[Any, ToolBackend, ToolContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    mode: ToolMode
    approval_required: bool
    timeout_seconds: float
    input_model: type[BaseModel]
    handler: Handler

    def describe(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        required = set(schema.get("required", []))
        inputs = []
        for name, prop in schema.get("properties", {}).items():
            kind = prop.get("type")
            if kind is None and "anyOf" in prop:
                kind = next((item.get("type") for item in prop["anyOf"] if item.get("type") != "null"), "string")
            inputs.append(
                {
                    "name": name,
                    "type": kind or "string",
                    "description": prop.get("description", ""),
                    "required": name in required,
                }
            )
        return {
            "name": self.name,
            "description": self.description,
            "mode": str(self.mode),
            "approval_required": self.approval_required,
            "inputs": inputs,
        }

    def json_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.input_model.model_validate(arguments).model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class ToolResult:
    tool: str
    phase: Phase
    ok: bool
    arguments: dict[str, Any]
    data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0
    quarantined: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "phase": self.phase,
            "ok": self.ok,
            "arguments": self.arguments,
            "data": self.data,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "quarantined": self.quarantined,
        }
