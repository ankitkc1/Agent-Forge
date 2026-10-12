"""Runtime dependencies shared by every node (model, tools, retrieval, memory, policy)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.agent import blueprint
from src.agent.contracts import StepConfig
from src.agent.llm import ChatModel, build_model, complete_structured
from src.agent.prompts import render_user_prompt, system_prompt
from src.config import Settings, get_settings
from src.guardrails.policy import ActionPolicy
from src.memory.store import MemoryStore, build_memory
from src.rag.retriever import Retriever, build_retriever
from src.tools.backends import build_backend
from src.tools.base import ToolBackend
from src.tools.registry import ToolRegistry

_UNSET: Any = object()


@dataclass
class AgentRuntime:
    settings: Settings
    model: ChatModel
    backend: ToolBackend
    tools: ToolRegistry
    retriever: Retriever | None
    memory: MemoryStore
    policy: ActionPolicy

    @classmethod
    async def create(
        cls,
        settings: Settings | None = None,
        *,
        model: ChatModel | None = None,
        backend: ToolBackend | None = None,
        retriever: Retriever | None = _UNSET,
        memory: MemoryStore | None = None,
    ) -> AgentRuntime:
        settings = settings or get_settings()
        backend = backend or build_backend(settings)
        registry = ToolRegistry(backend, redact_logs=blueprint.GUARDRAILS["redact_logs"])
        if retriever is _UNSET:
            retriever = await build_retriever(settings)
        return cls(
            settings=settings,
            model=model or build_model(settings),
            backend=backend,
            tools=registry,
            retriever=retriever,
            memory=memory or build_memory(settings),
            policy=ActionPolicy(registry, max_actions=blueprint.GUARDRAILS["max_tool_calls"]),
        )

    async def structured[T: BaseModel](
        self, task: str, step: StepConfig | None, context: dict[str, Any], output: type[T]
    ) -> T:
        return await complete_structured(
            self.model,
            task=task,
            system=system_prompt(),
            user=render_user_prompt(task, step, context),
            context=context,
            output=output,
        )
