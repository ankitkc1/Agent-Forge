"""HTTP routes: runs, approvals, memory erasure, health and metrics."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.agent import blueprint
from src.agent.contracts import ApprovalDecision
from src.agent.service import (
    AgentService,
    RunNotAwaitingApprovalError,
    RunNotFoundError,
    RunView,
)
from src.api.schemas import ApprovalRequest, HealthResponse, RunRequest
from src.api.security import Principal, require_approver, require_caller

router = APIRouter()


def get_service(request: Request) -> AgentService:
    return request.app.state.service


Service = Annotated[AgentService, Depends(get_service)]


@router.get("/health", response_model=HealthResponse, tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        agent=blueprint.AGENT_NAME,
        spec_sha256=blueprint.SPEC_SHA256,
        version=blueprint.AGENTFORGE_VERSION,
    )


@router.get("/ready", tags=["operations"])
async def ready(service: Service) -> dict[str, object]:
    runtime = service.runtime
    knowledge = await runtime.retriever.store.count() if runtime.retriever else None
    return {
        "status": "ready",
        "model": runtime.model.name,
        "tools": len(runtime.tools.names()),
        "knowledge_chunks": knowledge,
    }


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post("/v1/runs", response_model=RunView, tags=["runs"])
async def start_run(
    payload: RunRequest,
    request: Request,
    service: Service,
    principal: Annotated[Principal, Depends(require_caller)],
) -> RunView:
    if len(payload.message) > service.runtime.settings.request_max_chars:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "message too long")
    return await service.start(
        payload.message,
        thread_id=payload.thread_id,
        request_id=request.state.request_id,
    )


@router.get("/v1/runs/{run_id}", response_model=RunView, tags=["runs"])
async def get_run(
    run_id: str,
    service: Service,
    principal: Annotated[Principal, Depends(require_caller)],
    include_audit: Annotated[bool, Query()] = False,
) -> RunView:
    try:
        return await service.get(run_id, include_audit=include_audit)
    except RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found") from exc


@router.post("/v1/runs/{run_id}/approval", response_model=RunView, tags=["runs"])
async def decide(
    run_id: str,
    payload: ApprovalRequest,
    service: Service,
    principal: Annotated[Principal, Depends(require_approver)],
) -> RunView:
    decision = ApprovalDecision(
        approved=payload.approved,
        reviewer=f"{payload.reviewer} (key {principal.key_id})",
        comment=payload.comment,
        action_ids=payload.action_ids,
    )
    try:
        return await service.resume(run_id, decision)
    except RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found") from exc
    except RunNotAwaitingApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "run is not awaiting approval") from exc


@router.delete("/v1/threads/{thread_id}/memory", tags=["privacy"])
async def erase_thread(
    thread_id: str,
    service: Service,
    principal: Annotated[Principal, Depends(require_approver)],
) -> dict[str, int]:
    return {"deleted": await service.runtime.memory.forget(thread_id)}
