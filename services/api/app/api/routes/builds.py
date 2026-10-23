from __future__ import annotations

import asyncio
import base64
import contextlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

import anyio
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import DbSession
from app.compiler import spec_hash
from app.core.config import get_settings
from app.core.security import CurrentPrincipal
from app.db.session import SessionLocal
from app.models.build import BuildRecord
from app.schemas.build import BuildCreate, BuildEventRead, BuildPage, BuildRead, FileContent, FileEntry
from app.services import builds as service
from app.services.artifacts import (
    ArtifactAccessError,
    artifact_sha256,
    list_files,
    read_file,
    resolve_artifact,
)
from app.tasks.pipeline import run_build

router = APIRouter(prefix="/builds", tags=["builds"])
STREAM_INTERVAL_SECONDS = 0.75
STREAM_MAX_SECONDS = 30 * 60


def _owner(principal: CurrentPrincipal) -> str | None:
    # Development mode is intentionally a shared workspace. Authenticated deployments are private
    # per principal; returning 404 avoids disclosing whether another user's build exists.
    return None if principal.method == "none" else principal.id


def _get_or_404(db: DbSession, build_id: uuid.UUID, principal: CurrentPrincipal) -> BuildRecord:
    record = service.get_build(db, build_id, requested_by=_owner(principal))
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build not found")
    return record


def _dispatch(db: DbSession, record: BuildRecord) -> None:
    if get_settings().build_dispatch == "inline":
        from app.services.dispatch import submit_inline

        record.task_id = f"inline:{record.id}"
        db.commit()
        submit_inline(str(record.id))
        return
    try:
        result = run_build.apply_async(args=[str(record.id)], task_id=str(record.id))
    except Exception as exc:
        service.mark_dispatch_failed(db, record)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "build queue unavailable") from exc
    record.task_id = getattr(result, "id", None) or str(record.id)
    db.commit()


@router.post("", response_model=BuildRead, status_code=status.HTTP_202_ACCEPTED)
def create_build(
    payload: BuildCreate,
    db: DbSession,
    principal: CurrentPrincipal,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> BuildRead:
    canonical = spec_hash(payload.spec)
    if canonical != payload.spec_hash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "AgentSpec hash mismatch; compile or revalidate the specification before building",
        )
    try:
        record, created = service.create_build(
            db,
            get_settings(),
            spec=payload.spec,
            spec_hash=canonical,
            requested_by=principal.id,
            idempotency_key=idempotency_key,
        )
    except service.BuildConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.CapacityError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(exc), headers={"Retry-After": "30"}
        ) from exc
    if created:
        _dispatch(db, record)
    else:
        response.status_code = status.HTTP_200_OK
    return service.to_read(db, record)


@router.get("", response_model=BuildPage)
def list_builds(
    db: DbSession,
    principal: CurrentPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
    status_filter: Annotated[
        Literal["queued", "running", "succeeded", "failed", "cancelled"] | None, Query(alias="status")
    ] = None,
    agent: Annotated[str | None, Query(max_length=80)] = None,
) -> BuildPage:
    try:
        records, next_cursor = service.list_builds(
            db,
            limit=limit,
            cursor=cursor,
            status=status_filter,
            agent=agent,
            requested_by=_owner(principal),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor") from exc
    return BuildPage(items=[service.to_summary(record) for record in records], next_cursor=next_cursor)


@router.get("/{build_id}", response_model=BuildRead)
def get_build(build_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal) -> BuildRead:
    return service.to_read(db, _get_or_404(db, build_id, principal))


@router.get("/{build_id}/events", response_model=list[BuildEventRead])
def get_events(
    build_id: uuid.UUID,
    db: DbSession,
    principal: CurrentPrincipal,
    after: Annotated[int, Query(ge=0)] = 0,
) -> list[BuildEventRead]:
    _get_or_404(db, build_id, principal)
    return [BuildEventRead.model_validate(event) for event in service.events_after(db, build_id, after)]


@router.get("/{build_id}/report")
def get_report(build_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    return service.report_payload(_get_or_404(db, build_id, principal))


@router.get("/{build_id}/stream")
async def stream_build(
    build_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> StreamingResponse:
    owner = _owner(principal)

    def snapshot(after: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        with SessionLocal() as session:
            record = service.get_build(session, build_id, requested_by=owner)
            if record is None:
                return None, []
            build = service.to_read(session, record).model_dump(mode="json")
            events = [
                BuildEventRead.model_validate(event).model_dump(mode="json")
                for event in service.events_after(session, build_id, after)
            ]
            return build, events

    initial, _ = await anyio.to_thread.run_sync(snapshot, 0)
    if initial is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build not found")

    async def events() -> AsyncIterator[str]:
        last_event = max((event["id"] for event in initial["events"]), default=0)
        last_update = initial["updated_at"]
        yield f"event: build\ndata: {json.dumps(initial)}\n\n"
        elapsed = 0.0
        while elapsed < STREAM_MAX_SECONDS and initial["status"] not in {"succeeded", "failed", "cancelled"}:
            if await request.is_disconnected():
                return
            await asyncio.sleep(STREAM_INTERVAL_SECONDS)
            elapsed += STREAM_INTERVAL_SECONDS
            build, new_events = await anyio.to_thread.run_sync(snapshot, last_event)
            if build is None:
                return
            for event in new_events:
                last_event = event["id"]
                yield f"event: log\ndata: {json.dumps(event)}\n\n"
            if build["updated_at"] != last_update:
                last_update = build["updated_at"]
                yield f"event: build\ndata: {json.dumps(build)}\n\n"
            if build["status"] in {"succeeded", "failed", "cancelled"}:
                yield "event: end\ndata: {}\n\n"
                return
            if not new_events:
                yield ": keep-alive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/{build_id}/cancel", response_model=BuildRead, status_code=status.HTTP_202_ACCEPTED)
def cancel_build(build_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal) -> BuildRead:
    record = _get_or_404(db, build_id, principal)
    try:
        record = service.request_cancel(db, record)
    except service.BuildConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if record.status == "cancelled" and record.task_id and not record.task_id.startswith("inline:"):
        # If the broker is unavailable the worker still honours cancel_requested.
        with contextlib.suppress(Exception):
            run_build.app.control.revoke(record.task_id)
    return service.to_read(db, record)


@router.post("/{build_id}/retry", response_model=BuildRead, status_code=status.HTTP_202_ACCEPTED)
def retry_build(build_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal) -> BuildRead:
    original = _get_or_404(db, build_id, principal)
    if not original.terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, "only finished builds can be retried")
    from app.schemas.agent_spec import AgentSpec

    spec = AgentSpec.model_validate(original.spec)
    try:
        record, _ = service.create_build(
            db,
            get_settings(),
            spec=spec,
            spec_hash=spec_hash(spec),
            requested_by=principal.id,
            parent_build_id=original.id,
        )
    except service.CapacityError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    _dispatch(db, record)
    return service.to_read(db, record)


@router.delete("/{build_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_build(build_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal) -> Response:
    record = _get_or_404(db, build_id, principal)
    try:
        service.delete_build(db, record, get_settings().artifact_root)
    except service.BuildConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _artifact_or_error(record: BuildRecord):  # type: ignore[no-untyped-def]
    if not record.artifact_ready:
        raise HTTPException(status.HTTP_409_CONFLICT, "artifact is not ready")
    try:
        artifact = resolve_artifact(get_settings().artifact_root, record.artifact_path)
    except ArtifactAccessError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if record.artifact_sha256:
        actual = artifact_sha256(artifact)
        if not hmac.compare_digest(actual, record.artifact_sha256):
            raise HTTPException(status.HTTP_409_CONFLICT, "artifact failed its integrity check")
    return artifact


@router.get("/{build_id}/files", response_model=list[FileEntry])
def get_files(build_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal) -> list[FileEntry]:
    return list_files(_artifact_or_error(_get_or_404(db, build_id, principal)))


@router.get("/{build_id}/files/{path:path}", response_model=FileContent)
def get_file(build_id: uuid.UUID, path: str, db: DbSession, principal: CurrentPrincipal) -> FileContent:
    artifact = _artifact_or_error(_get_or_404(db, build_id, principal))
    try:
        return read_file(artifact, path)
    except ArtifactAccessError as exc:
        code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE if "binary" in str(exc) else status.HTTP_404_NOT_FOUND
        raise HTTPException(code, str(exc)) from exc


@router.get("/{build_id}/artifact")
def download_artifact(build_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal) -> FileResponse:
    record = _get_or_404(db, build_id, principal)
    artifact = _artifact_or_error(record)
    filename = f"{record.agent_name.replace('_', '-')}-agent-{str(record.id)[:8]}.zip"
    headers = {}
    if record.artifact_sha256:
        digest = base64.b64encode(bytes.fromhex(record.artifact_sha256)).decode()
        headers["X-Artifact-SHA256"] = record.artifact_sha256
        headers["Digest"] = f"sha-256={digest}"
        headers["Content-Digest"] = f"sha-256=:{digest}:"
    return FileResponse(artifact, media_type="application/zip", filename=filename, headers=headers)
