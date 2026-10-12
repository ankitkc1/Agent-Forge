"""Model layer: JSON extraction, structured-output retries and provider request shapes."""

from __future__ import annotations

import json

import httpx
import pytest

from src.agent import llm
from src.agent.contracts import ClassificationOutput
from src.agent.llm import (
    AnthropicModel,
    ModelError,
    OpenAICompatibleModel,
    ScriptedModel,
    complete_structured,
    extract_json,
)
from tests.support import run


def test_extract_json_tolerates_fences_and_preambles() -> None:
    assert extract_json('Sure!\n```json\n{"label": "a", "nested": {"x": "}"}}\n```') == {
        "label": "a",
        "nested": {"x": "}"},
    }
    with pytest.raises(ModelError):
        extract_json("no json here")


def test_structured_output_retries_with_validation_feedback() -> None:
    model = ScriptedModel(responses=["not json", {"label": "billing", "confidence": 0.8}])
    output = run(
        complete_structured(model, task="classify", system="s", user="u", context={}, output=ClassificationOutput)
    )
    assert output.label == "billing"
    assert len(model.calls) == 2
    assert "not valid for the required schema" in model.calls[1]["messages"][-1]["content"]


def test_structured_output_fails_closed() -> None:
    model = ScriptedModel(responses=["bad", '{"confidence": 2}'])
    with pytest.raises(ModelError):
        run(complete_structured(model, task="classify", system="s", user="u", context={}, output=ClassificationOutput))


class _Recorder:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


@pytest.fixture
def mock_http(monkeypatch: pytest.MonkeyPatch):
    def install(responses: list[httpx.Response]) -> _Recorder:
        recorder = _Recorder(responses)
        original = httpx.AsyncClient

        def factory(*args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["transport"] = httpx.MockTransport(recorder)
            return original(*args, **kwargs)

        monkeypatch.setattr(llm.httpx, "AsyncClient", factory)

        async def no_sleep(_: float) -> None:
            return None

        monkeypatch.setattr(llm.asyncio, "sleep", no_sleep)
        return recorder

    return install


def test_openai_request_shape_and_retry(mock_http) -> None:  # type: ignore[no-untyped-def]
    body = {"choices": [{"message": {"content": '{"response": "ok"}'}}]}
    recorder = mock_http([httpx.Response(429, json={}), httpx.Response(200, json=body)])
    model = OpenAICompatibleModel(name="openai", model="gpt-4.1-mini", temperature=0.1, max_output_tokens=256, timeout=5, api_key="sk-test")
    text = run(model.complete([{"role": "user", "content": "hi"}], task="respond", context={}))
    assert json.loads(text) == {"response": "ok"}
    sent = json.loads(recorder.requests[-1].content)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["max_completion_tokens"] == 256
    assert recorder.requests[-1].headers["Authorization"] == "Bearer sk-test"
    assert len(recorder.requests) == 2


def test_anthropic_request_shape(mock_http) -> None:  # type: ignore[no-untyped-def]
    body = {"content": [{"type": "text", "text": '{"response": "ok"}'}]}
    recorder = mock_http([httpx.Response(200, json=body)])
    model = AnthropicModel(name="anthropic", model="claude-test", temperature=0.1, max_output_tokens=256, timeout=5, api_key="key")
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}]
    assert json.loads(run(model.complete(messages, task="respond", context={}))) == {"response": "ok"}
    request = recorder.requests[0]
    sent = json.loads(request.content)
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert sent["system"].startswith("rules")
    assert sent["messages"] == [{"role": "user", "content": "hi"}]


def test_provider_errors_surface_as_model_errors(mock_http) -> None:  # type: ignore[no-untyped-def]
    mock_http([httpx.Response(401, json={"error": "bad key"})])
    model = OpenAICompatibleModel(name="local", model="qwen", temperature=0.1, max_output_tokens=64, timeout=5)
    with pytest.raises(ModelError, match="401"):
        run(model.complete([{"role": "user", "content": "hi"}], task="respond", context={}))
