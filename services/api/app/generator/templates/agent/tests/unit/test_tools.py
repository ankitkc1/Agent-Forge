"""Tool registry: allowlist, input validation, phase enforcement, timeouts."""

from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest

from src.agent.runtime import AgentRuntime
from src.tools.base import ToolContext, ToolMode, ToolNotAllowedError
from src.tools.registry import ToolRegistry, assert_allowed
from tests.support import ROOT, run

CTX = ToolContext(run_id="test", thread_id="test", request_id="test", phase="read")


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(ToolNotAllowedError):
        assert_allowed("shell_exec")


def test_registry_rejects_definitions_outside_allowlist(runtime: AgentRuntime) -> None:
    definition = runtime.tools.get(runtime.tools.names()[0])
    rogue = dataclasses.replace(definition, name="rm_rf")
    with pytest.raises(ToolNotAllowedError):
        ToolRegistry(runtime.backend, definitions=[rogue])


def test_invalid_arguments_fail_closed(runtime: AgentRuntime) -> None:
    for name in runtime.tools.names():
        definition = runtime.tools.get(name)
        phase = "read" if definition.mode == ToolMode.READ else "execute"
        result = run(runtime.tools.invoke(name, {"unexpected_field": 1}, phase=phase, ctx=CTX))
        assert not result.ok
        assert "invalid arguments" in (result.error or "")


def test_read_tools_return_fixture_records(runtime: AgentRuntime) -> None:
    if not runtime.tools.names(ToolMode.READ):
        pytest.skip("agent has no read tools")
    fixtures = json.loads((ROOT / "data" / "fixtures" / "tools.json").read_text(encoding="utf-8"))
    for name in runtime.tools.names(ToolMode.READ):
        spec = fixtures["tools"].get(name, {})
        key, records = spec.get("key"), spec.get("records", [])
        arguments = {key: records[0][key]} if key and records else {}
        for item in runtime.tools.get(name).describe()["inputs"]:
            if item["required"] and item["name"] not in arguments:
                arguments[item["name"]] = "test"
        result = run(runtime.tools.invoke(name, arguments, phase="read", ctx=CTX))
        assert result.ok, result.error
        assert result.data is not None
        if key and records:
            assert result.data["found"] is True
        else:
            assert "results" in result.data or "found" in result.data


def test_side_effect_tools_cannot_run_in_read_phase(runtime: AgentRuntime) -> None:
    for name in runtime.tools.names(ToolMode.DRAFT) + runtime.tools.names(ToolMode.EXECUTE):
        result = run(runtime.tools.invoke(name, {}, phase="read", ctx=CTX))
        assert not result.ok
        assert "cannot run in phase" in (result.error or "")


def test_execute_tools_cannot_preview(runtime: AgentRuntime) -> None:
    for name in runtime.tools.names(ToolMode.EXECUTE):
        result = run(runtime.tools.invoke(name, {}, phase="preview", ctx=CTX))
        assert not result.ok


def test_timeouts_are_enforced(runtime: AgentRuntime) -> None:
    name = runtime.tools.names()[0]
    definition = runtime.tools.get(name)

    async def slow_handler(arguments, backend, ctx):  # type: ignore[no-untyped-def]
        await asyncio.sleep(1)
        return {}

    fast = dataclasses.replace(definition, timeout_seconds=0.05, handler=slow_handler)
    registry = ToolRegistry(runtime.backend, definitions=[fast])
    arguments = {item["name"]: "P-1" for item in definition.describe()["inputs"] if item["type"] == "string"}
    for item in definition.describe()["inputs"]:
        if item["type"] in {"number", "integer"}:
            arguments[item["name"]] = 1
        if item["type"] == "boolean":
            arguments[item["name"]] = False
    phase = "read" if definition.mode == ToolMode.READ else "execute"
    result = run(registry.invoke(name, arguments, phase=phase, ctx=CTX))
    assert not result.ok
    assert "timeout" in (result.error or "")
