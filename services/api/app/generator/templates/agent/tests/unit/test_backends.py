"""Tool backends: the fixture journal and the HTTP integration-gateway contract."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from src.config import Settings
from src.tools import backends
from src.tools.backends import FixtureBackend, HttpBackend, build_backend
from src.tools.base import ToolContext, ToolError
from tests.support import run

CTX = ToolContext(run_id="run-1", thread_id="thread-1", request_id="req-1", phase="read")
Reply = httpx.Response | Exception


class Gateway:
    """Fake integration gateway that records every request."""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = replies
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Gateway]:
    def install(*replies: Reply) -> Gateway:
        recorder = Gateway(list(replies))
        original = httpx.AsyncClient

        def factory(*args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["transport"] = httpx.MockTransport(recorder)
            return original(*args, **kwargs)

        async def no_sleep(_: float) -> None:
            return None

        monkeypatch.setattr(backends.httpx, "AsyncClient", factory)
        monkeypatch.setattr(backends.asyncio, "sleep", no_sleep)
        return recorder

    return install


def test_http_read_contract(gateway: Callable[..., Gateway]) -> None:
    recorder = gateway(httpx.Response(200, json={"found": True}))
    backend = HttpBackend("https://gateway.internal/", "gateway-token")
    assert run(backend.call("lookup_record", "read", {"record_id": "REC-1"}, CTX)) == {"found": True}
    request = recorder.requests[0]
    assert str(request.url) == "https://gateway.internal/tools/lookup_record/read"
    assert request.headers["Authorization"] == "Bearer gateway-token"
    assert request.headers["X-Request-ID"] == "req-1"
    assert "Idempotency-Key" not in request.headers
    assert json.loads(request.content) == {"arguments": {"record_id": "REC-1"}, "run_id": "run-1", "request_id": "req-1"}


def test_reads_retry_transient_failures(gateway: Callable[..., Gateway]) -> None:
    recorder = gateway(httpx.Response(503), httpx.ConnectError("connection refused"), httpx.Response(200, json={"ok": 1}))
    assert run(HttpBackend("https://gw", None).call("lookup_record", "read", {}, CTX)) == {"ok": 1}
    assert len(recorder.requests) == 3
    assert "Authorization" not in recorder.requests[0].headers


def test_reads_give_up_after_retries(gateway: Callable[..., Gateway]) -> None:
    recorder = gateway(*(httpx.ConnectError("down") for _ in range(3)))
    with pytest.raises(ToolError, match="unavailable"):
        run(HttpBackend("https://gw", None, retries=2).call("lookup_record", "read", {}, CTX))
    assert len(recorder.requests) == 3


def test_client_errors_are_not_retried(gateway: Callable[..., Gateway]) -> None:
    recorder = gateway(httpx.Response(404, json={"detail": "unknown tool"}))
    with pytest.raises(ToolError, match="HTTP 404"):
        run(HttpBackend("https://gw", None).call("lookup_record", "read", {}, CTX))
    assert len(recorder.requests) == 1


def test_side_effects_are_idempotent_and_never_retried(gateway: Callable[..., Gateway]) -> None:
    recorder = gateway(httpx.Response(503), httpx.Response(200, json={"receipt_id": "R-1"}), httpx.Response(200, json={"receipt_id": "R-1"}))
    backend = HttpBackend("https://gw", "token")
    with pytest.raises(ToolError):
        run(backend.call("send_message", "execute", {"to": "a", "body": "b"}, CTX))
    assert len(recorder.requests) == 1  # a failed side effect is never replayed automatically
    run(backend.call("send_message", "execute", {"body": "b", "to": "a"}, CTX))
    run(backend.call("send_message", "execute", {"to": "a", "body": "b"}, CTX))
    keys = [request.headers["Idempotency-Key"] for request in recorder.requests]
    assert keys[0].startswith("run-1:send_message:") and len(set(keys)) == 1


def test_non_object_payloads_are_rejected(gateway: Callable[..., Gateway]) -> None:
    gateway(httpx.Response(200, json=["not", "an", "object"]))
    with pytest.raises(ToolError, match="non-object"):
        run(HttpBackend("https://gw", None).call("lookup_record", "read", {}, CTX))


def test_fixture_backend_journals_side_effects() -> None:
    backend = FixtureBackend(fixtures={"tools": {"lookup_record": {"key": "record_id", "records": [{"record_id": "REC-1", "owner": "Ops"}]}}})
    found = run(backend.call("lookup_record", "read", {"record_id": "rec-1"}, CTX))
    assert found == {"found": True, "record": {"record_id": "REC-1", "owner": "Ops"}}
    missing = run(backend.call("lookup_record", "read", {"record_id": "REC-9"}, CTX))
    assert missing["found"] is False and missing["record"] is None
    assert run(backend.call("unknown_tool", "read", {}, CTX))["found"] is False
    preview = run(backend.call("draft_reply", "preview", {"body": "hello"}, CTX))
    assert preview["status"] == "draft" and preview["draft_id"].startswith("DRAFT-")
    assert backend.journal == [] and len(backend.previews) == 1
    receipt = run(backend.call("send_reply", "execute", {"body": "hello"}, CTX))
    assert receipt["status"] == "executed"
    assert backend.journal == [{**receipt, "arguments": {"body": "hello"}, "run_id": "run-1"}]


def test_fixture_backend_free_text_search() -> None:
    records = [{"title": "Leaking roof"}, {"title": "Broken heater"}]
    backend = FixtureBackend(fixtures={"tools": {"search": {"records": records}}})
    result = run(backend.call("search", "read", {"query": "heater"}, CTX))
    assert result == {"found": True, "results": [{"title": "Broken heater"}]}


def test_build_backend_selection(settings: Settings) -> None:
    assert isinstance(build_backend(settings), FixtureBackend)
    with pytest.raises(ValueError, match="TOOL_BACKEND_URL"):
        build_backend(settings.model_copy(update={"tool_backend": "http"}))
    http = build_backend(
        settings.model_copy(update={"tool_backend": "http", "tool_backend_url": "https://gw/", "tool_backend_token": SecretStr("t")})
    )
    assert isinstance(http, HttpBackend) and http.base_url == "https://gw" and http.token == "t"
