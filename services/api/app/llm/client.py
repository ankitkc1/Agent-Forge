"""Minimal, dependency-light LLM client used by the optional compiler and repair features.

AgentForge works fully offline; configuring ``AGENTFORGE_LLM_PROVIDER`` only *adds* an LLM-backed
requirement analyzer and repair strategy. All model output is treated as untrusted data and must
pass the same schema validation and security policy as user input.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings


class LLMError(RuntimeError):
    pass


class JsonLLM(Protocol):
    name: str

    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict[str, Any]: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse the first balanced JSON object in ``text`` (tolerates code fences and preambles)."""
    cleaned = _FENCE.sub("", text.strip())
    start = cleaned.find("{")
    if start < 0:
        raise LLMError("model response did not contain a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError as exc:
                    raise LLMError(f"model returned invalid JSON: {exc}") from exc
                if not isinstance(value, dict):
                    raise LLMError("model returned JSON that is not an object")
                return value
    raise LLMError("model response contained an unterminated JSON object")


RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504, 529})


@dataclass
class _HttpModel:
    name: str
    model: str
    timeout: float
    retries: int = 2
    transport: httpx.BaseTransport | None = field(default=None, repr=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        last_error: str = "no attempt made"
        with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
            for attempt in range(self.retries + 1):
                delay = float(min(2**attempt, 10))
                try:
                    response = client.post(url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code < 400:
                        try:
                            payload = response.json()
                        except ValueError as exc:
                            raise LLMError(f"{self.name} returned a non-JSON response") from exc
                        if not isinstance(payload, dict):
                            raise LLMError(f"{self.name} returned an unexpected payload")
                        return payload
                    if response.status_code not in RETRYABLE_STATUS:
                        # Never echo request headers; the body of an error response is safe to show.
                        raise LLMError(
                            f"{self.name} returned HTTP {response.status_code}: {response.text[:300]}"
                        )
                    last_error = f"HTTP {response.status_code}"
                    retry_after = response.headers.get("retry-after", "")
                    if retry_after.isdigit():
                        delay = min(float(retry_after), 30.0)
                if attempt < self.retries:
                    self.sleep(delay)
        raise LLMError(f"{self.name} request failed after {self.retries + 1} attempt(s): {last_error}")


@dataclass
class OpenAICompatibleLLM(_HttpModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    json_mode: bool = True

    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_completion_tokens": max_tokens,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        payload = self._post(f"{self.base_url.rstrip('/')}/chat/completions", headers, body)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("unexpected chat completion payload") from exc
        return extract_json_object(str(content))


@dataclass
class AnthropicLLM(_HttpModel):
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"

    def complete_json(self, system: str, user: str, *, max_tokens: int = 4096) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system + "\nRespond with a single JSON object and nothing else.",
            "messages": [{"role": "user", "content": user}],
        }
        payload = self._post(f"{self.base_url.rstrip('/')}/v1/messages", headers, body)
        try:
            text = "".join(
                block.get("text", "") for block in payload["content"] if block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise LLMError("unexpected messages payload") from exc
        return extract_json_object(text)


def build_llm(settings: Settings) -> JsonLLM | None:
    provider = settings.llm_provider
    if provider == "none":
        return None
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    timeout = float(settings.llm_timeout_seconds)
    if provider == "openai":
        if not api_key:
            raise LLMError("AGENTFORGE_LLM_API_KEY is required for the openai provider")
        return OpenAICompatibleLLM(
            name="openai",
            model=settings.llm_model or "gpt-5-mini",
            timeout=timeout,
            base_url=settings.llm_base_url or "https://api.openai.com/v1",
            api_key=api_key,
        )
    if provider == "ollama":
        return OpenAICompatibleLLM(
            name="ollama",
            model=settings.llm_model or "qwen2.5:14b",
            timeout=timeout,
            base_url=settings.llm_base_url or "http://ollama:11434/v1",
            api_key=api_key,
        )
    if provider == "anthropic":
        if not api_key:
            raise LLMError("AGENTFORGE_LLM_API_KEY is required for the anthropic provider")
        return AnthropicLLM(
            name="anthropic",
            model=settings.llm_model or "claude-sonnet-5-5",
            timeout=timeout,
            api_key=api_key,
            base_url=settings.llm_base_url or "https://api.anthropic.com",
        )
    raise LLMError(f"unsupported LLM provider: {provider}")
