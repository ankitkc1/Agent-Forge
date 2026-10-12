from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, select

from app.api.deps import DbSession
from app.core.config import get_settings
from app.models.build import BuildRecord
from app.schemas.build import BuildCreate, BuildRead
from app.services.compiler import spec_hash
from app.services.pipeline import initial_stages
from app.tasks.pipeline import run_build

router = APIRouter(prefix="/builds", tags=["builds"])


def _get_or_404(db: DbSession, build_id: uuid.UUID) -> BuildRecord:
    record = db.scalar(select(BuildRecord).where(BuildRecord.id == build_id))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
    return record


@router.post("", response_model=BuildRead, status_code=status.HTTP_202_ACCEPTED)
def create_build(payload: BuildCreate, db: DbSession) -> BuildRecord:
    canonical_hash = spec_hash(payload.spec)
    if canonical_hash != payload.spec_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AgentSpec hash mismatch; compile or revalidate the specification before building"
            ),
        )
    record = BuildRecord(
        agent_name=payload.spec.agent.name,
        spec_hash=canonical_hash,
        spec=payload.spec.model_dump(mode="json"),
        status="queued",
        progress=0,
        stages=initial_stages(),
        logs=["AgentSpec hash verified", "Build accepted and queued"],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    try:
        run_build.delay(str(record.id))
    except Exception as exc:
        record.status = "failed"
        record.error = "build queue unavailable"
        record.logs = [*record.logs, "Queue dispatch failed safely"]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="build queue unavailable"
        ) from exc
    return record


@router.get("", response_model=list[BuildRead])
def list_builds(db: DbSession, limit: int = Query(default=20, ge=1, le=100)) -> list[BuildRecord]:
    return list(db.scalars(select(BuildRecord).order_by(desc(BuildRecord.created_at)).limit(limit)))


@router.get("/{build_id}", response_model=BuildRead)
def get_build(build_id: uuid.UUID, db: DbSession) -> BuildRecord:
    return _get_or_404(db, build_id)


@router.get("/{build_id}/artifact")
def download_artifact(build_id: uuid.UUID, db: DbSession) -> FileResponse:
    record = _get_or_404(db, build_id)
    if not record.artifact_ready or not record.artifact_path:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="artifact is not ready")
    root = get_settings().artifact_root.resolve()
    artifact = Path(record.artifact_path).resolve()
    if not artifact.is_relative_to(root) or not artifact.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    filename = f"{record.agent_name.replace('_', '-')}-agent-{str(record.id)[:8]}.zip"
    return FileResponse(artifact, media_type="application/zip", filename=filename)
