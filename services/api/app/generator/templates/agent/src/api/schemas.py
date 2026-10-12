"""HTTP request contracts (responses reuse ``RunView`` from the agent service)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=100_000)
    thread_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,128}$")


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str | None = Field(default=None, max_length=2000)
    action_ids: list[str] | None = Field(default=None, max_length=50)


class HealthResponse(BaseModel):
    status: str
    agent: str
    spec_sha256: str
    version: str
