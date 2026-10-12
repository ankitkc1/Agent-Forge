"""Application service around the compiled graph: start runs, resume approvals, read state.

A *run* is one request processed by the graph (its LangGraph thread id is the run id). A *thread*
is a conversation: memory stores the turns of a thread so later runs see recent history.
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.types import Command
from pydantic import BaseModel, Field

from src.agent.blueprint import STEPS
from src.agent.contracts import ApprovalDecision, RunStatus
from src.agent.runtime import AgentRuntime

APPROVAL_NODES = frozenset(step_id for step_id, step in STEPS.items() if step.kind == "human_approval")


class RunNotFoundError(LookupError):
    pass


class RunNotAwaitingApprovalError(RuntimeError):
    pass


class PendingApproval(BaseModel):
    actions: list[dict[str, Any]] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    draft_response: str = ""


class RunView(BaseModel):
    run_id: str
    thread_id: str
    status: RunStatus
    response: str | None = None
    classification: dict[str, Any] | None = None
    assessments: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    executed_actions: list[dict[str, Any]] = Field(default_factory=list)
    pending_approval: PendingApproval | None = None
    approval: dict[str, Any] | None = None
    block_reasons: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    security_events: int = 0
    audit: list[dict[str, Any]] | None = None


class AgentService:
    def __init__(self, runtime: AgentRuntime, graph: Any) -> None:
        self.runtime = runtime
        self.graph = graph

    @staticmethod
    def _config(run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}, "recursion_limit": 64}

    async def start(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> RunView:
        run_id = run_id or f"run_{uuid.uuid4().hex[:24]}"
        thread_id = thread_id or f"thr_{uuid.uuid4().hex[:24]}"
        history = await self.runtime.memory.history(thread_id)
        initial = {
            "run_id": run_id,
            "thread_id": thread_id,
            "request_id": request_id or uuid.uuid4().hex,
            "user_input": message,
            "history": history,
            "status": "running",
        }
        result = await self.graph.ainvoke(initial, self._config(run_id))
        view = self._view(run_id, result, result.get("__interrupt__"))
        await self.runtime.memory.append(thread_id, "user", message)
        if view.status != "awaiting_approval" and view.response:
            await self.runtime.memory.append(thread_id, "assistant", view.response)
        return view

    async def resume(self, run_id: str, decision: ApprovalDecision) -> RunView:
        snapshot = await self.graph.aget_state(self._config(run_id))
        if not snapshot.values:
            raise RunNotFoundError(run_id)
        if not snapshot.next or not set(snapshot.next) <= APPROVAL_NODES:
            raise RunNotAwaitingApprovalError(run_id)
        result = await self.graph.ainvoke(
            Command(resume=decision.model_dump(mode="json")), self._config(run_id)
        )
        view = self._view(run_id, result, result.get("__interrupt__"))
        if view.status != "awaiting_approval" and view.response:
            await self.runtime.memory.append(view.thread_id, "assistant", view.response)
        return view

    async def get(self, run_id: str, *, include_audit: bool = False) -> RunView:
        snapshot = await self.graph.aget_state(self._config(run_id))
        if not snapshot.values:
            raise RunNotFoundError(run_id)
        interrupts = snapshot.interrupts if snapshot.next else ()
        return self._view(run_id, snapshot.values, interrupts, include_audit=include_audit)

    @staticmethod
    def _view(
        run_id: str, values: dict[str, Any], interrupts: Any, *, include_audit: bool = False
    ) -> RunView:
        pending = None
        status: RunStatus = values.get("status", "running")
        if interrupts:
            payload = getattr(interrupts[0], "value", interrupts[0]) or {}
            status = "awaiting_approval"
            pending = PendingApproval(
                actions=list(payload.get("actions", [])),
                review_reasons=list(payload.get("review_reasons", [])),
                draft_response=str(payload.get("draft_response", "")),
            )
        citations = [
            {key: item[key] for key in ("citation", "source", "title", "document", "score")}
            for item in values.get("evidence", [])
        ]
        return RunView(
            run_id=run_id,
            thread_id=values.get("thread_id", ""),
            status=status,
            response=values.get("final_response") if status != "awaiting_approval" else None,
            classification=values.get("classification"),
            assessments=values.get("assessments") or {},
            citations=citations,
            tool_results=[
                {"tool": r["tool"], "ok": r["ok"], "error": r.get("error"), "quarantined": r.get("quarantined", False)}
                for r in values.get("tool_results", [])
            ],
            proposed_actions=[
                {key: action.get(key) for key in ("id", "tool", "mode", "arguments", "preview", "requires_approval", "rationale")}
                for action in values.get("proposed_actions", [])
            ],
            executed_actions=list(values.get("executed_actions", [])),
            pending_approval=pending,
            approval=values.get("approval"),
            block_reasons=list(values.get("block_reasons", [])),
            review_reasons=list(values.get("review_reasons", [])),
            security_events=len(values.get("security_events", [])),
            audit=list(values.get("audit_log", [])) if include_audit else None,
        )
