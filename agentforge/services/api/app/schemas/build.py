from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_spec import AgentSpec


class BuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: AgentSpec
    spec_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class PipelineStage(BaseModel):
    key: str
    name: str
    status: Literal["pending", "running", "passed", "failed", "skipped"]
    progress: float = Field(ge=0, le=100)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: str | None = None


class BuildMetrics(BaseModel):
    task_success: float = Field(ge=0, le=1)
    tool_accuracy: float = Field(ge=0, le=1)
    unsafe_actions: int = Field(ge=0)
    test_coverage: float = Field(ge=0, le=1)
    tests_passed: int = Field(ge=0)


class BuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    agent_name: str
    spec_hash: str
    progress: float
    current_stage: str | None
    stages: list[PipelineStage]
    logs: list[str]
    metrics: BuildMetrics | None
    artifact_ready: bool
    error: str | None
    created_at: datetime
    updated_at: datetime
