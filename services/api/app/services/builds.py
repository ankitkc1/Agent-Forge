"""Build lifecycle operations shared by the HTTP API and maintenance tasks."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import and_, delete, desc, func, or_, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import Settings
from app.models.build import TERMINAL_STATUSES, BuildEvent, BuildRecord
from app.schemas.agent_spec import AgentSpec
from app.schemas.build import BuildEventRead, BuildRead, BuildSummary, PipelineStage
from app.services.pipeline import initial_stages

logger = structlog.get_logger(__name__)
LOG_TAIL = 200


class BuildConflictError(RuntimeError):
    pass


class CapacityError(RuntimeError):
    pass


def get_build(
    session: Session, build_id: uuid.UUID, *, requested_by: str | None = None
) -> BuildRecord | None:
    statement = select(BuildRecord).where(BuildRecord.id == build_id)
    if requested_by is not None:
        statement = statement.where(BuildRecord.requested_by == requested_by)
    return session.scalar(statement)


def _lock_build_admission(session: Session) -> None:
    """Serialize capacity and idempotency checks across PostgreSQL API workers."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(1095911762)"))


def create_build(
    session: Session,
    settings: Settings,
    *,
    spec: AgentSpec,
    spec_hash: str,
    requested_by: str | None,
    idempotency_key: str | None = None,
    parent_build_id: uuid.UUID | None = None,
) -> tuple[BuildRecord, bool]:
    """Return (record, created). Re-using an idempotency key returns the existing build."""
    _lock_build_admission(session)
    if idempotency_key:
        existing = session.scalar(
            select(BuildRecord).where(
                BuildRecord.requested_by == requested_by,
                BuildRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.spec_hash != spec_hash:
                raise BuildConflictError("Idempotency-Key was already used for a different specification")
            return existing, False
    active = session.scalar(
        select(func.count()).select_from(BuildRecord).where(BuildRecord.status.in_(("queued", "running")))
    )
    if (active or 0) >= settings.max_active_builds:
        raise CapacityError(f"{active} builds are already active; try again shortly")
    record = BuildRecord(
        agent_name=spec.agent.name,
        spec_hash=spec_hash,
        spec=spec.model_dump(mode="json"),
        status="queued",
        progress=0.0,
        stages=initial_stages(),
        requested_by=requested_by,
        idempotency_key=idempotency_key,
        parent_build_id=parent_build_id,
        agentforge_version=__version__,
    )
    session.add(record)
    session.flush()
    session.add(
        BuildEvent(build_id=record.id, level="info", message="AgentSpec hash verified; build queued.")
    )
    session.commit()
    session.refresh(record)
    return record, True


def mark_dispatch_failed(session: Session, record: BuildRecord) -> None:
    record.status = "failed"
    record.error = "build queue unavailable"
    record.finished_at = datetime.now(UTC)
    session.add(
        BuildEvent(
            build_id=record.id, level="error", message="Queue dispatch failed; the build was not started."
        )
    )
    session.commit()


def request_cancel(session: Session, record: BuildRecord) -> BuildRecord:
    if record.status in TERMINAL_STATUSES:
        raise BuildConflictError(f"build is already {record.status}")
    record.cancel_requested = True
    if record.status == "queued":
        record.status = "cancelled"
        record.finished_at = datetime.now(UTC)
        record.current_stage = "Cancelled"
        record.stages = [{**stage, "status": "cancelled"} for stage in record.stages]
    session.add(BuildEvent(build_id=record.id, level="warning", message="Cancellation requested."))
    session.commit()
    session.refresh(record)
    return record


def delete_build(session: Session, record: BuildRecord, artifact_root: Path) -> None:
    if record.status not in TERMINAL_STATUSES:
        raise BuildConflictError("cancel the build before deleting it")
    _remove_artifact(record, artifact_root)
    session.execute(delete(BuildEvent).where(BuildEvent.build_id == record.id))
    session.delete(record)
    session.commit()


def _remove_artifact(record: BuildRecord, artifact_root: Path) -> None:
    if not record.artifact_path:
        return
    artifact = Path(record.artifact_path).resolve()
    if artifact.is_relative_to(artifact_root.resolve()):
        artifact.unlink(missing_ok=True)


def purge_expired(session: Session, settings: Settings) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=settings.build_retention_days)
    expired = list(
        session.scalars(
            select(BuildRecord).where(
                BuildRecord.created_at < cutoff, BuildRecord.status.in_(tuple(TERMINAL_STATUSES))
            )
        )
    )
    for record in expired:
        _remove_artifact(record, settings.artifact_root)
        session.execute(delete(BuildEvent).where(BuildEvent.build_id == record.id))
        session.delete(record)
    session.commit()
    if expired:
        logger.info("builds_purged", count=len(expired), cutoff=cutoff.isoformat())
    return len(expired)


# --------------------------------------------------------------------------------------------
# listing & serialisation
# --------------------------------------------------------------------------------------------


def encode_cursor(record: BuildRecord) -> str:
    payload = json.dumps({"t": record.created_at.isoformat(), "i": str(record.id)})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded.encode()))
    return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])


def list_builds(
    session: Session,
    *,
    limit: int,
    cursor: str | None = None,
    status: str | None = None,
    agent: str | None = None,
    requested_by: str | None = None,
) -> tuple[list[BuildRecord], str | None]:
    statement = select(BuildRecord).order_by(desc(BuildRecord.created_at), desc(BuildRecord.id))
    if requested_by is not None:
        statement = statement.where(BuildRecord.requested_by == requested_by)
    if status:
        statement = statement.where(BuildRecord.status == status)
    if agent:
        statement = statement.where(BuildRecord.agent_name.contains(agent))
    if cursor:
        created_at, build_id = decode_cursor(cursor)
        statement = statement.where(
            or_(
                BuildRecord.created_at < created_at,
                and_(BuildRecord.created_at == created_at, BuildRecord.id < build_id),
            )
        )
    rows = list(session.scalars(statement.limit(limit + 1)))
    next_cursor = encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor


def events_after(session: Session, build_id: uuid.UUID, after: int = 0, limit: int = 500) -> list[BuildEvent]:
    return list(
        session.scalars(
            select(BuildEvent)
            .where(BuildEvent.build_id == build_id, BuildEvent.id > after)
            .order_by(BuildEvent.id)
            .limit(limit)
        )
    )


def to_summary(record: BuildRecord) -> BuildSummary:
    return BuildSummary.model_validate(record)


def to_read(session: Session, record: BuildRecord) -> BuildRead:
    tail = list(
        reversed(
            list(
                session.scalars(
                    select(BuildEvent)
                    .where(BuildEvent.build_id == record.id)
                    .order_by(desc(BuildEvent.id))
                    .limit(LOG_TAIL)
                )
            )
        )
    )
    summary = BuildSummary.model_validate(record).model_dump()
    return BuildRead(
        **summary,
        stages=[PipelineStage.model_validate(stage) for stage in record.stages],
        logs=[event.message for event in tail],
        events=[BuildEventRead.model_validate(event) for event in tail],
        artifact_sha256=record.artifact_sha256,
        artifact_size=record.artifact_size,
        agentforge_version=record.agentforge_version,
        cancel_requested=record.cancel_requested,
    )


def report_payload(record: BuildRecord) -> dict[str, Any]:
    return record.report or {}
