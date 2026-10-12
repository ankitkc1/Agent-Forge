"""Typed contracts shared by the graph, the model layer and the API."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["running", "awaiting_approval", "completed", "blocked", "rejected", "failed"]


@dataclass(frozen=True)
class LabelConfig:
    name: str
    description: str = ""
    hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepConfig:
    id: str
    kind: str
    description: str = ""
    tools: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    labels: tuple[LabelConfig, ...] = ()
    dimension: str | None = None
    review: str = "when_required"


# --------------------------------------------------------------------------------------------
# Structured model outputs. Every model response is validated against one of these.
# --------------------------------------------------------------------------------------------


class _Output(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ClassificationOutput(_Output):
    label: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""


class AssessmentOutput(_Output):
    level: str
    rationale: str = ""


class ToolArgumentsOutput(_Output):
    arguments: dict[str, Any] = Field(default_factory=dict)


class AnalysisOutput(_Output):
    summary: str
    findings: list[str] = Field(default_factory=list)


class ProposedActionOutput(_Output):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class DraftOutput(_Output):
    summary: str = ""
    message: str = ""
    actions: list[ProposedActionOutput] = Field(default_factory=list)


class VerificationOutput(_Output):
    supported: bool
    issues: list[str] = Field(default_factory=list)


class ResponseOutput(_Output):
    response: str


# --------------------------------------------------------------------------------------------
# Approval contract
# --------------------------------------------------------------------------------------------


class ApprovalDecision(BaseModel):
    """A reviewer's decision. ``action_ids`` approves a subset; omitted means all pending."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str | None = Field(default=None, max_length=2000)
    action_ids: list[str] | None = Field(default=None, max_length=50)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def action_digest(tool: str, arguments: dict[str, Any]) -> str:
    """SHA-256 over the exact tool name and arguments. Approvals bind to this digest."""
    return hashlib.sha256(f"{tool}\n{canonical_json(arguments)}".encode()).hexdigest()
