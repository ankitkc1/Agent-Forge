"""MCP server: exposes read-only tools and runs, never side-effecting tools."""

from __future__ import annotations

import json

import pytest

from src.agent.service import AgentService
from src.tools.base import ToolMode
from tests.support import run

pytest.importorskip("mcp.server.mcpserver")

from src import mcp_server


@pytest.fixture
def server(service: AgentService, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    async def fake_service() -> AgentService:
        return service

    monkeypatch.setattr(mcp_server, "get_service", fake_service)
    return mcp_server.create_server()


def test_only_safe_tools_are_exposed(server, service: AgentService) -> None:  # type: ignore[no-untyped-def]
    names = {tool.name for tool in run(server.list_tools())}
    assert set(service.runtime.tools.names(ToolMode.READ)) <= names
    side_effecting = set(service.runtime.tools.names(ToolMode.DRAFT)) | set(service.runtime.tools.names(ToolMode.EXECUTE))
    assert not names & side_effecting
    assert {"run_agent", "get_run"} <= names


def test_read_tool_can_be_called(server, service: AgentService) -> None:  # type: ignore[no-untyped-def]
    read_tools = service.runtime.tools.names(ToolMode.READ)
    if not read_tools:
        pytest.skip("agent has no read tools")
    definition = service.runtime.tools.get(read_tools[0])
    arguments = {}
    for item in definition.describe()["inputs"]:
        if item["required"]:
            arguments[item["name"]] = {"number": 1.0, "integer": 1, "boolean": False}.get(item["type"], "P-1001")
    result = run(server.call_tool(read_tools[0], arguments))
    payload = json.loads(result.content[0].text)
    assert payload["tool"] == read_tools[0]
    assert payload["phase"] == "read"


def test_run_agent_tool(server) -> None:  # type: ignore[no-untyped-def]
    result = run(server.call_tool("run_agent", {"message": "Hello, I have a question about my account."}))
    payload = json.loads(result.content[0].text)
    assert payload["status"] in {"completed", "awaiting_approval", "blocked"}
