"""Allowlist-backed tool registry with input validation, phase checks, timeouts and auditing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from typing import Any

import structlog
from pydantic import ValidationError

from src.guardrails.pii import redact_value
from src.observability import TOOL_CALLS, TOOL_LATENCY
from src.tools.base import (
    ALLOWED_PHASES,
    Phase,
    ToolBackend,
    ToolContext,
    ToolDefinition,
    ToolError,
    ToolInputError,
    ToolMode,
    ToolNotAllowedError,
    ToolPhaseError,
    ToolResult,
    ToolTimeoutError,
)
from src.tools.catalog import DEFINITIONS, ToolName

logger = structlog.get_logger(__name__)


def assert_allowed(name: str) -> ToolName:
    try:
        return ToolName(name)
    except ValueError as exc:
        raise ToolNotAllowedError(f"Tool is not allowlisted: {name}") from exc


class ToolRegistry:
    def __init__(
        self,
        backend: ToolBackend,
        *,
        definitions: Iterable[ToolDefinition] = DEFINITIONS,
        redact_logs: bool = True,
    ) -> None:
        self.backend = backend
        self.redact_logs = redact_logs
        self._definitions = {definition.name: definition for definition in definitions}
        unknown = set(self._definitions) - {tool.value for tool in ToolName}
        if unknown:
            raise ToolNotAllowedError(f"definitions outside the allowlist: {sorted(unknown)}")

    def get(self, name: str) -> ToolDefinition:
        return self._definitions[assert_allowed(name).value]

    def names(self, mode: ToolMode | None = None) -> list[str]:
        return [name for name, d in self._definitions.items() if mode is None or d.mode == mode]

    def describe(self, names: Iterable[str]) -> list[dict[str, Any]]:
        return [self.get(name).describe() for name in names]

    async def invoke(
        self, name: str, arguments: dict[str, Any], *, phase: Phase, ctx: ToolContext
    ) -> ToolResult:
        started = time.perf_counter()
        try:
            definition = self.get(name)
            if phase not in ALLOWED_PHASES[definition.mode]:
                raise ToolPhaseError(f"{name} ({definition.mode}) cannot run in phase '{phase}'")
            try:
                parsed = definition.input_model.model_validate(arguments)
            except ValidationError as exc:
                fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
                raise ToolInputError(f"invalid arguments for {name}: {fields}") from exc
            call_ctx = ToolContext(ctx.run_id, ctx.thread_id, ctx.request_id, phase)
            try:
                async with asyncio.timeout(definition.timeout_seconds):
                    data = await definition.handler(parsed, self.backend, call_ctx)
            except TimeoutError as exc:
                raise ToolTimeoutError(
                    f"{name} exceeded {definition.timeout_seconds:.0f}s timeout"
                ) from exc
            if not isinstance(data, dict):
                raise ToolError(f"{name} returned {type(data).__name__}, expected an object")
            result = ToolResult(
                tool=name,
                phase=phase,
                ok=True,
                arguments=parsed.model_dump(mode="json", exclude_none=True),
                data=data,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except ToolError as exc:
            result = ToolResult(
                tool=name,
                phase=phase,
                ok=False,
                arguments=arguments,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:  # backend failures must not crash the run
            logger.exception("tool_backend_error", tool=name, phase=phase)
            result = ToolResult(
                tool=name,
                phase=phase,
                ok=False,
                arguments=arguments,
                error=f"{type(exc).__name__}: tool backend failed",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        TOOL_CALLS.labels(name if name in self._definitions else "unknown", phase, "ok" if result.ok else "error").inc()
        TOOL_LATENCY.labels(phase).observe(result.duration_ms / 1000)
        logger.info(
            "tool_call",
            tool=name,
            phase=phase,
            ok=result.ok,
            duration_ms=round(result.duration_ms, 1),
            run_id=ctx.run_id,
            arguments=redact_value(result.arguments) if self.redact_logs else result.arguments,
            error=result.error,
        )
        return result
