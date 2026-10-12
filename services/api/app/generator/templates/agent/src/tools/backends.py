"""Tool backends.

``FixtureBackend`` serves deterministic sample data from ``data/fixtures/tools.json`` and keeps
an in-memory *journal* of every side effect, which tests and evaluations use to prove that
nothing executes before approval. ``HttpBackend`` forwards calls to your integration gateway:

    POST {TOOL_BACKEND_URL}/tools/{tool}/{phase}
    Authorization: Bearer {TOOL_BACKEND_TOKEN}
    Idempotency-Key: {run_id}:{tool}:{digest}         (execute phase)
    {"arguments": {...}, "run_id": "...", "request_id": "..."}

Implement that small contract in front of your systems of record, or replace a tool's
``handle`` function to call an SDK directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.agent.contracts import action_digest
from src.config import Settings
from src.tools.base import Phase, ToolBackend, ToolContext, ToolError


class FixtureBackend:
    def __init__(self, fixtures_path: Path | None = None, fixtures: dict[str, Any] | None = None):
        if fixtures is None:
            fixtures = {}
            if fixtures_path and fixtures_path.is_file():
                fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
        self.tools: dict[str, Any] = dict(fixtures.get("tools", {}))
        self.journal: list[dict[str, Any]] = []
        self.previews: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def call(
        self, tool: str, phase: Phase, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        digest = action_digest(tool, arguments)[:12]
        if phase == "read":
            return self._read(tool, arguments)
        if phase == "preview":
            preview = {"draft_id": f"DRAFT-{digest}", "status": "draft", "tool": tool, "content": arguments}
            async with self._lock:
                self.previews.append({**preview, "run_id": ctx.run_id})
            return preview
        receipt = {
            "receipt_id": f"RCPT-{digest}",
            "status": "executed",
            "tool": tool,
            "executed_at": datetime.now(UTC).isoformat(),
        }
        async with self._lock:
            self.journal.append({**receipt, "arguments": arguments, "run_id": ctx.run_id})
        return receipt

    def _read(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self.tools.get(tool)
        if spec is None:
            return {"found": False, "message": f"No fixture data configured for {tool}."}
        key = spec.get("key")
        records = spec.get("records", [])
        if key and arguments.get(key) is not None:
            wanted = str(arguments[key]).strip().casefold()
            for record in records:
                if str(record.get(key, "")).casefold() == wanted:
                    return {"found": True, "record": record}
            return {"found": False, "record": None, "message": f"No record with {key}={arguments[key]}."}
        query = str(next(iter(arguments.values()), "")).casefold()
        matches = [r for r in records if query and query in json.dumps(r).casefold()]
        return {"found": bool(matches or records), "results": (matches or records)[:3]}


class HttpBackend:
    def __init__(self, base_url: str, token: str | None, *, timeout: float = 30.0, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retries = retries

    async def call(
        self, tool: str, phase: Phase, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "X-Request-ID": ctx.request_id}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if phase == "execute":
            digest = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()[:16]
            headers["Idempotency-Key"] = f"{ctx.run_id}:{tool}:{digest}"
        body = {"arguments": arguments, "run_id": ctx.run_id, "request_id": ctx.request_id}
        attempts = self.retries + 1 if phase == "read" else 1
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(
                        f"{self.base_url}/tools/{tool}/{phase}", json=body, headers=headers
                    )
                except httpx.HTTPError as exc:
                    last = exc
                else:
                    if response.status_code >= 500 and attempt + 1 < attempts:
                        last = ToolError(f"gateway HTTP {response.status_code}")
                    elif response.status_code >= 400:
                        raise ToolError(f"{tool} gateway HTTP {response.status_code}")
                    else:
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise ToolError(f"{tool} gateway returned a non-object payload")
                        return payload
                await asyncio.sleep(min(2**attempt * 0.5, 5))
        raise ToolError(f"{tool} gateway unavailable: {last}")


def build_backend(settings: Settings) -> ToolBackend:
    if settings.tool_backend == "http":
        if not settings.tool_backend_url:
            raise ValueError("TOOL_BACKEND_URL is required when TOOL_BACKEND=http")
        token = settings.tool_backend_token.get_secret_value() if settings.tool_backend_token else None
        return HttpBackend(settings.tool_backend_url, token)
    return FixtureBackend(settings.fixtures_path)
