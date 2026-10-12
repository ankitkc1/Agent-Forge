"""Architecture plan contracts produced by the planner and consumed by the generator and UI."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]
SEVERITY_ORDER: dict[str, int] = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class PlanNode(BaseModel):
    id: str
    kind: str
    title: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    platform: bool = False
    side_effects: bool = False
    order: int


class PlanEdge(BaseModel):
    source: str
    target: str
    condition: str | None = None


class ToolParameterPlan(BaseModel):
    name: str
    type: str
    description: str
    required: bool


class ToolBinding(BaseModel):
    name: str
    description: str
    mode: Literal["read", "draft", "execute"]
    approval_required: bool
    timeout_seconds: int
    inputs: list[ToolParameterPlan]
    used_by: list[str]
    phases: list[str]


class TopologyCheck(BaseModel):
    id: str
    title: str
    passed: bool
    detail: str


class RiskFinding(BaseModel):
    id: str
    severity: Severity
    title: str
    detail: str
    mitigation: str
    status: Literal["mitigated", "accepted", "open"]
    blocking: bool = False


class RiskReport(BaseModel):
    level: Severity
    blocking: bool
    findings: list[RiskFinding]


class Component(BaseModel):
    id: str
    title: str
    technology: str
    detail: str


class ArchitecturePlan(BaseModel):
    schema_version: Literal["agentforge.plan/v1"] = "agentforge.plan/v1"
    agent: str
    nodes: list[PlanNode]
    edges: list[PlanEdge]
    tools: list[ToolBinding]
    checks: list[TopologyCheck]
    risk: RiskReport
    components: list[Component]
    mermaid: str

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks) and not self.risk.blocking
