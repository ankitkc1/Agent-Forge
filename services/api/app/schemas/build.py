from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.agent_spec import AgentSpec


def _assume_utc(value: datetime) -> datetime:
    """SQLite drops time zones; every timestamp AgentForge writes is UTC, so say so explicitly."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_assume_utc)]

BuildStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
StageStatus = Literal["pending", "running", "passed", "failed", "skipped", "cancelled"]


class BuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: AgentSpec
    spec_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class PipelineStage(BaseModel):
    key: str
    name: str
    status: StageStatus
    progress: float = Field(ge=0, le=100)
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    summary: str | None = None
    attempts: int = 0


class BuildMetrics(BaseModel):
    task_success: float = Field(ge=0, le=1)
    tool_accuracy: float = Field(ge=0, le=1)
    unsafe_actions: int = Field(ge=0)
    test_coverage: float = Field(ge=0, le=1)
    tests_passed: int = Field(ge=0)
    tests_total: int = Field(default=0, ge=0)
    tests_failed: int = Field(default=0, ge=0)
    eval_cases: int = Field(default=0, ge=0)
    adversarial_cases: int = Field(default=0, ge=0)
    security_findings: int = Field(default=0, ge=0)
    repair_attempts: int = Field(default=0, ge=0)
    files: int = Field(default=0, ge=0)
    eval_mode: str = "offline"


class BuildEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: UtcDatetime
    level: str
    stage: str | None
    message: str


class BuildSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: BuildStatus
    agent_name: str
    spec_hash: str
    progress: float
    current_stage: str | None
    metrics: BuildMetrics | None
    artifact_ready: bool
    error: str | None
    requested_by: str | None
    attempt: int
    parent_build_id: uuid.UUID | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    duration_seconds: float | None


class BuildRead(BuildSummary):
    stages: list[PipelineStage]
    logs: list[str] = Field(default_factory=list)
    events: list[BuildEventRead] = Field(default_factory=list)
    artifact_sha256: str | None = None
    artifact_size: int | None = None
    agentforge_version: str | None = None
    cancel_requested: bool = False


class BuildPage(BaseModel):
    items: list[BuildSummary]
    next_cursor: str | None = None


class FileEntry(BaseModel):
    path: str
    size: int
    sha256: str | None = None
    evidence: bool = False


class FileContent(BaseModel):
    path: str
    size: int
    content: str
    language: str
    truncated: bool = False
