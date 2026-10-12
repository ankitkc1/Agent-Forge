"""Model providers behind one small async interface.

* ``openai``    - OpenAI Chat Completions API.
* ``local``     - any OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp server).
* ``anthropic`` - Anthropic Messages API.
* ``offline``   - deterministic heuristics with no network access (tests, evals, demos).

Every response is parsed as JSON and validated against a Pydantic model; invalid output is
retried once with the validation error, then rejected. Model output is never executed.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict

import httpx
from pydantic import BaseModel, ValidationError

from src.config import Settings

_REASONING_MODEL = re.compile(r"^(o\d|gpt-5)", re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class Message(TypedDict):
    role: str
    content: str


class ModelError(RuntimeError):
    """The provider failed or returned output that could not be validated."""


class ChatModel(Protocol):
    name: str

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        task: str,
        context: Mapping[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> str: ...


def extract_json(text: str) -> Any:
    """Parse the first JSON object in ``text``; tolerates code fences and short preambles."""
    cleaned = _FENCE.sub("", text.strip())
    start = cleaned.find("{")
    if start < 0:
        raise ModelError("response did not contain a JSON object")
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError as exc:
                    raise ModelError(f"invalid JSON: {exc}") from exc
    raise ModelError("unterminated JSON object")


async def complete_structured[T: BaseModel](
    model: ChatModel,
    *,
    task: str,
    system: str,
    user: str,
    context: Mapping[str, Any],
    output: type[T],
    retries: int = 1,
) -> T:
    schema = output.model_json_schema()
    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: Exception | None = None
    for _ in range(retries + 1):
        raw = await model.complete(messages, task=task, context=context, schema=schema)
        try:
            return output.model_validate(extract_json(raw))
        except (ModelError, ValidationError) as exc:
            last_error = exc
            messages = [
                *messages,
                {"role": "assistant", "content": raw[:4000]},
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not valid for the required schema: "
                        f"{str(exc)[:800]}\nReply again with only a JSON object matching: "
                        f"{json.dumps(schema)[:3000]}"
                    ),
                },
            ]
    raise ModelError(f"{model.name} returned invalid {task} output: {last_error}")


@dataclass
class _HttpModel:
    name: str
    model: str
    temperature: float
    max_output_tokens: int
    timeout: float
    max_retries: int = 3

    async def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.post(url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    last = exc
                else:
                    if response.status_code in {408, 409, 429, 500, 502, 503, 504}:
                        last = ModelError(f"HTTP {response.status_code}")
                        retry_after = response.headers.get("retry-after", "")
                        delay = float(retry_after) if retry_after.isdigit() else 2**attempt
                        await asyncio.sleep(min(delay, 20))
                        continue
                    if response.status_code >= 400:
                        raise ModelError(
                            f"{self.name} HTTP {response.status_code}: {response.text[:400]}"
                        )
                    return response.json()
                await asyncio.sleep(min(2**attempt, 20))
        raise ModelError(f"{self.name} request failed after {self.max_retries} attempts: {last}")


@dataclass
class OpenAICompatibleModel(_HttpModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    json_mode: bool = True

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        task: str,
        context: Mapping[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict[str, Any] = {"model": self.model, "messages": list(messages)}
        if self.name == "openai":
            body["max_completion_tokens"] = self.max_output_tokens
            if not _REASONING_MODEL.match(self.model):
                body["temperature"] = self.temperature
        else:
            body["max_tokens"] = self.max_output_tokens
            body["temperature"] = self.temperature
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        payload = await self._post(f"{self.base_url.rstrip('/')}/chat/completions", headers, body)
        try:
            return str(payload["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("unexpected chat completion payload") from exc


@dataclass
class AnthropicModel(_HttpModel):
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        task: str,
        context: Mapping[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        conversation = [
            {"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"
        ]
        body = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "system": system + "\n\nRespond with a single JSON object only.",
            "messages": conversation,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = await self._post(f"{self.base_url.rstrip('/')}/v1/messages", headers, body)
        try:
            return "".join(
                block.get("text", "") for block in payload["content"] if block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise ModelError("unexpected messages payload") from exc


@dataclass
class ScriptedModel:
    """Test double: returns queued responses or computes them from (task, context)."""

    responses: list[str | dict[str, Any]] = field(default_factory=list)
    handler: Callable[[str, Mapping[str, Any]], str | dict[str, Any]] | None = None
    name: str = "scripted"
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        task: str,
        context: Mapping[str, Any],
        schema: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append({"task": task, "messages": list(messages), "context": dict(context)})
        if self.responses:
            item = self.responses.pop(0)
        elif self.handler is not None:
            item = self.handler(task, context)
        else:
            raise ModelError("scripted model has no response queued")
        return item if isinstance(item, str) else json.dumps(item)


def build_model(settings: Settings) -> ChatModel:
    provider = settings.model_provider
    common = {
        "model": settings.model_name,
        "temperature": settings.model_temperature,
        "max_output_tokens": settings.model_max_output_tokens,
        "timeout": settings.model_timeout_seconds,
    }
    if provider == "offline":
        from src.agent.offline import OfflineModel

        return OfflineModel()
    if provider == "openai":
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        if not key:
            raise ModelError("OPENAI_API_KEY is required when MODEL_PROVIDER=openai")
        return OpenAICompatibleModel(
            name="openai",
            base_url=settings.model_base_url or "https://api.openai.com/v1",
            api_key=key,
            **common,
        )
    if provider == "local":
        return OpenAICompatibleModel(
            name="local",
            base_url=settings.model_base_url or "http://localhost:11434/v1",
            api_key=None,
            **common,
        )
    if provider == "anthropic":
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
        if not key:
            raise ModelError("ANTHROPIC_API_KEY is required when MODEL_PROVIDER=anthropic")
        return AnthropicModel(
            name="anthropic",
            base_url=settings.model_base_url or "https://api.anthropic.com",
            api_key=key,
            **common,
        )
    raise ModelError(f"unsupported model provider: {provider}")
